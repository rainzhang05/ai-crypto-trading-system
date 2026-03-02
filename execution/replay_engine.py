"""Deterministic runtime execution orchestration and replay harness."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from typing import Any, Mapping, Optional, Protocol, Sequence
from uuid import UUID

from execution.activation_gate import enforce_activation_gate
from execution.decision_engine import (
    NUMERIC_18,
    NUMERIC_10,
    deterministic_decision,
    normalize_decimal,
    stable_hash,
)
from execution.deterministic_context import (
    DeterministicAbortError,
    DeterministicContextBuilder,
    ExecutionContext,
    PredictionState,
    PriorEconomicState,
    RunContextState,
)
from execution.exchange_adapter import OrderAttemptRequest
from execution.exchange_simulator import DeterministicExchangeSimulator
from execution.risk_runtime import (
    RiskViolation,
    RuntimeRiskProfile,
    compute_volatility_adjusted_fraction,
    enforce_capital_preservation,
    enforce_cluster_cap,
    enforce_cross_account_isolation,
    enforce_position_count_cap,
    enforce_runtime_risk_gate,
    enforce_severe_loss_entry_gate,
    evaluate_adaptive_horizon_action,
    evaluate_risk_state_machine,
    evaluate_severe_loss_recovery_action,
)
from execution.runtime_writer import (
    AppendOnlyRuntimeWriter,
    CashLedgerRow,
    ClusterExposureHourlyStateRow,
    ExecutedTradeRow,
    OrderFillRow,
    OrderRequestRow,
    PortfolioHourlyStateRow,
    PositionLotRow,
    RiskEventRow,
    RiskHourlyStateRow,
    RuntimeWriteResult,
    TradeSignalRow,
)


class RuntimeDatabase(Protocol):
    """Combined read/write DB protocol needed by execute/replay functions."""

    def fetch_one(self, sql: str, params: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        """Fetch one row."""

    def fetch_all(self, sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        """Fetch all rows."""

    def execute(self, sql: str, params: Mapping[str, Any]) -> None:
        """Execute SQL mutation."""


@dataclass(frozen=True)
class ReplayMismatch:
    table_name: str
    key: str
    field_name: str
    expected: str
    actual: str


@dataclass(frozen=True)
class ReplayReport:
    mismatch_count: int
    mismatches: tuple[ReplayMismatch, ...]


@dataclass(frozen=True)
class _OrderIntent:
    side: str
    requested_qty: Decimal
    requested_notional: Decimal
    source_reason_code: str


@dataclass(frozen=True)
class _LotView:
    lot_id: UUID
    asset_id: int
    open_ts_utc: datetime
    open_price: Decimal
    open_qty: Decimal
    open_fee: Decimal
    open_slippage_cost: Decimal
    parent_lot_hash: str
    historical_consumed_qty: Decimal


@dataclass(frozen=True)
class _Phase5HourlyStateResult:
    portfolio_row: PortfolioHourlyStateRow
    risk_row: RiskHourlyStateRow
    cluster_rows: tuple[ClusterExposureHourlyStateRow, ...]


_RETRY_BACKOFF_MINUTES: tuple[int, ...] = (1, 2, 4)


def execute_hour(
    db: RuntimeDatabase,
    run_id: UUID,
    account_id: int,
    run_mode: str,
    hour_ts_utc: datetime,
    risk_profile: Optional[RuntimeRiskProfile] = None,
) -> RuntimeWriteResult:
    """Execute deterministic runtime writes for one run/account/hour key."""
    builder = DeterministicContextBuilder(db)
    writer = AppendOnlyRuntimeWriter(db)

    begin = getattr(db, "begin", None)
    commit = getattr(db, "commit", None)
    rollback = getattr(db, "rollback", None)
    tx_started = False

    try:
        if callable(begin):
            begin()
            tx_started = True

        # Preserve and validate ledger continuity before writes.
        writer.assert_ledger_continuity(
            account_id=account_id,
            run_mode=run_mode,
        )

        phase5_state = _ensure_phase5_hourly_state(
            db=db,
            builder=builder,
            writer=writer,
            run_id=run_id,
            account_id=account_id,
            run_mode=run_mode,
            hour_ts_utc=hour_ts_utc,
        )
        context = builder.build_context(run_id, account_id, run_mode, hour_ts_utc)
        planned = _plan_runtime_artifacts(
            context=context,
            writer=writer,
            risk_profile=risk_profile,
        )

        for signal in planned.trade_signals:
            writer.insert_trade_signal(signal)
        for order in planned.order_requests:
            writer.insert_order_request(order)
        for fill in planned.order_fills:
            writer.insert_order_fill(fill)
        for lot in planned.position_lots:
            writer.insert_position_lot(lot)
        for trade in planned.executed_trades:
            writer.insert_executed_trade(trade)
        for risk_event in planned.risk_events:
            writer.insert_risk_event(risk_event)

        cash_rows = _ensure_phase5_cash_ledger_rows(
            db=db,
            writer=writer,
            context=context,
            order_requests=planned.order_requests,
            order_fills=planned.order_fills,
            prior_ledger_state=context.prior_economic_state,
        )

        # Preserve and validate ledger continuity after writes.
        writer.assert_ledger_continuity(
            account_id=context.run_context.account_id,
            run_mode=context.run_context.run_mode,
        )

        if tx_started and callable(commit):
            commit()
        return RuntimeWriteResult(
            trade_signals=planned.trade_signals,
            order_requests=planned.order_requests,
            order_fills=planned.order_fills,
            position_lots=planned.position_lots,
            executed_trades=planned.executed_trades,
            risk_events=planned.risk_events,
            cash_ledger_rows=cash_rows,
            portfolio_hourly_states=(phase5_state.portfolio_row,),
            cluster_exposure_hourly_states=phase5_state.cluster_rows,
            risk_hourly_states=(phase5_state.risk_row,),
        )
    except Exception:
        if tx_started and callable(rollback):
            rollback()
        raise


def replay_hour(
    db: RuntimeDatabase,
    run_id: UUID,
    account_id: int,
    hour_ts_utc: datetime,
    risk_profile: Optional[RuntimeRiskProfile] = None,
) -> ReplayReport:
    """Reconstruct, recompute, and compare deterministic runtime artifacts."""
    run_ctx = db.fetch_one(
        """
        SELECT run_mode
        FROM run_context
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :hour_ts_utc
        """,
        {"run_id": str(run_id), "account_id": account_id, "hour_ts_utc": hour_ts_utc},
    )
    if run_ctx is None:
        raise DeterministicAbortError("run_context not found for replay key.")

    run_mode = str(run_ctx["run_mode"])
    builder = DeterministicContextBuilder(db)
    writer = AppendOnlyRuntimeWriter(db)
    phase5_state = _build_expected_phase5_hourly_state(
        db=db,
        builder=builder,
        writer=writer,
        run_id=run_id,
        account_id=account_id,
        run_mode=run_mode,
        hour_ts_utc=hour_ts_utc,
    )
    context = builder.build_context(run_id, account_id, run_mode, hour_ts_utc)
    expected = _plan_runtime_artifacts(
        context=context,
        writer=writer,
        risk_profile=risk_profile,
    )
    expected_cash_rows = _build_expected_cash_ledger_rows(
        writer=writer,
        context=context,
        order_requests=expected.order_requests,
        order_fills=expected.order_fills,
        prior_ledger_state=context.prior_economic_state,
    )

    stored_signals = db.fetch_all(
        """
        SELECT signal_id, decision_hash, row_hash
        FROM trade_signal
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND hour_ts_utc = :hour_ts_utc
        ORDER BY signal_id ASC
        """,
        {"run_id": str(run_id), "account_id": account_id, "hour_ts_utc": hour_ts_utc},
    )
    stored_orders = db.fetch_all(
        """
        SELECT order_id, row_hash
        FROM order_request
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :hour_ts_utc
        ORDER BY order_id ASC
        """,
        {"run_id": str(run_id), "account_id": account_id, "hour_ts_utc": hour_ts_utc},
    )
    stored_fills = db.fetch_all(
        """
        SELECT fill_id, row_hash
        FROM order_fill
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :hour_ts_utc
        ORDER BY fill_id ASC
        """,
        {"run_id": str(run_id), "account_id": account_id, "hour_ts_utc": hour_ts_utc},
    )
    stored_lots = db.fetch_all(
        """
        SELECT lot_id, row_hash
        FROM position_lot
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :hour_ts_utc
        ORDER BY lot_id ASC
        """,
        {"run_id": str(run_id), "account_id": account_id, "hour_ts_utc": hour_ts_utc},
    )
    stored_trades = db.fetch_all(
        """
        SELECT trade_id, row_hash
        FROM executed_trade
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :hour_ts_utc
        ORDER BY trade_id ASC
        """,
        {"run_id": str(run_id), "account_id": account_id, "hour_ts_utc": hour_ts_utc},
    )
    stored_risk_events = db.fetch_all(
        """
        SELECT risk_event_id, row_hash
        FROM risk_event
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :hour_ts_utc
        ORDER BY risk_event_id ASC
        """,
        {"run_id": str(run_id), "account_id": account_id, "hour_ts_utc": hour_ts_utc},
    )
    stored_cash_rows = db.fetch_all(
        """
        SELECT ledger_seq, row_hash
        FROM cash_ledger
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :hour_ts_utc
        ORDER BY ledger_seq ASC
        """,
        {"run_id": str(run_id), "account_id": account_id, "hour_ts_utc": hour_ts_utc},
    )
    stored_portfolio_rows = db.fetch_all(
        """
        SELECT hour_ts_utc, row_hash
        FROM portfolio_hourly_state
        WHERE source_run_id = :run_id
          AND account_id = :account_id
          AND run_mode = :run_mode
          AND hour_ts_utc = :hour_ts_utc
        ORDER BY hour_ts_utc ASC
        """,
        {
            "run_id": str(run_id),
            "account_id": account_id,
            "run_mode": run_mode,
            "hour_ts_utc": hour_ts_utc,
        },
    )
    stored_cluster_rows = db.fetch_all(
        """
        SELECT cluster_id, row_hash
        FROM cluster_exposure_hourly_state
        WHERE source_run_id = :run_id
          AND account_id = :account_id
          AND run_mode = :run_mode
          AND hour_ts_utc = :hour_ts_utc
        ORDER BY cluster_id ASC
        """,
        {
            "run_id": str(run_id),
            "account_id": account_id,
            "run_mode": run_mode,
            "hour_ts_utc": hour_ts_utc,
        },
    )
    stored_risk_rows = db.fetch_all(
        """
        SELECT hour_ts_utc, row_hash
        FROM risk_hourly_state
        WHERE source_run_id = :run_id
          AND account_id = :account_id
          AND run_mode = :run_mode
          AND hour_ts_utc = :hour_ts_utc
        ORDER BY hour_ts_utc ASC
        """,
        {
            "run_id": str(run_id),
            "account_id": account_id,
            "run_mode": run_mode,
            "hour_ts_utc": hour_ts_utc,
        },
    )

    mismatches: list[ReplayMismatch] = []
    mismatches.extend(_compare_signals(expected.trade_signals, stored_signals))
    mismatches.extend(_compare_orders(expected.order_requests, stored_orders))
    mismatches.extend(_compare_fills(expected.order_fills, stored_fills))
    mismatches.extend(_compare_lots(expected.position_lots, stored_lots))
    mismatches.extend(_compare_trades(expected.executed_trades, stored_trades))
    mismatches.extend(_compare_risk_events(expected.risk_events, stored_risk_events))
    mismatches.extend(_compare_cash_ledger(expected_cash_rows, stored_cash_rows))
    mismatches.extend(_compare_portfolio_hourly_states((phase5_state.portfolio_row,), stored_portfolio_rows))
    mismatches.extend(
        _compare_cluster_exposure_hourly_states(phase5_state.cluster_rows, stored_cluster_rows)
    )
    mismatches.extend(_compare_risk_hourly_states((phase5_state.risk_row,), stored_risk_rows))

    return ReplayReport(mismatch_count=len(mismatches), mismatches=tuple(mismatches))


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _build_expected_phase5_hourly_state(
    db: RuntimeDatabase,
    builder: DeterministicContextBuilder,
    writer: AppendOnlyRuntimeWriter,
    run_id: UUID,
    account_id: int,
    run_mode: str,
    hour_ts_utc: datetime,
) -> _Phase5HourlyStateResult:
    normalized_mode = run_mode.upper()
    run_context = builder._load_run_context(run_id, account_id, normalized_mode, hour_ts_utc)

    prediction_rows = db.fetch_all(
        """
        SELECT asset_id
        FROM model_prediction
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND run_mode = :run_mode
          AND hour_ts_utc = :hour_ts_utc
        ORDER BY asset_id ASC
        """,
        {
            "run_id": str(run_id),
            "account_id": account_id,
            "run_mode": normalized_mode,
            "hour_ts_utc": hour_ts_utc,
        },
    )
    predicted_assets = {int(row["asset_id"]) for row in prediction_rows}
    if not predicted_assets:
        raise DeterministicAbortError("No model_prediction rows available for execution hour.")

    position_rows = db.fetch_all(
        """
        SELECT asset_id, quantity
        FROM position_hourly_state
        WHERE run_mode = :run_mode
          AND account_id = :account_id
          AND hour_ts_utc = :hour_ts_utc
          AND source_run_id = :source_run_id
        ORDER BY asset_id ASC
        """,
        {
            "run_mode": normalized_mode,
            "account_id": account_id,
            "hour_ts_utc": hour_ts_utc,
            "source_run_id": str(run_id),
        },
    )
    open_inventory_assets: set[int] = set()
    position_qty_by_asset: dict[int, Decimal] = {}
    for row in position_rows:
        asset_id = int(row["asset_id"])
        quantity = normalize_decimal(_to_decimal(row["quantity"]), NUMERIC_18)
        position_qty_by_asset[asset_id] = quantity
        if quantity > 0:
            open_inventory_assets.add(asset_id)

    required_assets = sorted(predicted_assets | open_inventory_assets)
    memberships = _load_active_memberships(db, required_assets, hour_ts_utc)

    prior_ledger = builder.load_prior_ledger_state(account_id, normalized_mode, hour_ts_utc)
    prior_portfolio = builder.load_prior_portfolio_state(account_id, normalized_mode, hour_ts_utc)
    prior_risk = builder.load_prior_risk_state(account_id, normalized_mode, hour_ts_utc)
    _ = builder.load_prior_cluster_states(account_id, normalized_mode, hour_ts_utc)

    cash_balance = _resolve_starting_cash_balance(
        builder=builder,
        run_context=run_context,
        run_mode=normalized_mode,
        prior_ledger=prior_ledger,
        prior_portfolio=prior_portfolio,
    )

    market_value = Decimal("0").quantize(NUMERIC_18)
    cluster_notional: dict[int, Decimal] = {}
    open_position_count = 0
    for asset_id, quantity in sorted(position_qty_by_asset.items()):
        if quantity <= 0:
            continue
        mark_price = _resolve_mark_price(
            db=db,
            account_id=account_id,
            run_mode=normalized_mode,
            asset_id=asset_id,
            hour_ts_utc=hour_ts_utc,
        )
        if mark_price is None:
            raise DeterministicAbortError(
                f"Unable to determine mark price for held asset_id={asset_id} at {hour_ts_utc}."
            )
        mark_notional = normalize_decimal(quantity * mark_price, NUMERIC_18)
        market_value = normalize_decimal(market_value + mark_notional, NUMERIC_18)
        cluster_id = memberships[asset_id]
        previous_cluster = cluster_notional.get(cluster_id, Decimal("0").quantize(NUMERIC_18))
        cluster_notional[cluster_id] = normalize_decimal(previous_cluster + mark_notional, NUMERIC_18)
        open_position_count += 1

    provisional_portfolio_value = normalize_decimal(cash_balance + market_value, NUMERIC_18)
    peak_candidates = [provisional_portfolio_value]
    if prior_portfolio is not None:
        peak_candidates.append(prior_portfolio.peak_portfolio_value)
    if prior_risk is not None:
        peak_candidates.append(prior_risk.peak_portfolio_value)
    peak_value = normalize_decimal(max(peak_candidates), NUMERIC_18)

    max_total_exposure_pct = (
        prior_risk.max_total_exposure_pct if prior_risk is not None else Decimal("0.2000000000")
    )
    max_cluster_exposure_pct = (
        prior_risk.max_cluster_exposure_pct if prior_risk is not None else Decimal("0.0800000000")
    )
    kill_switch_active = prior_risk.kill_switch_active if prior_risk is not None else False
    kill_switch_reason = prior_risk.kill_switch_reason if prior_risk is not None else None

    risk_row = writer.build_risk_hourly_state_row(
        run_seed_hash=run_context.run_seed_hash,
        run_mode=normalized_mode,
        account_id=account_id,
        hour_ts_utc=hour_ts_utc,
        source_run_id=run_id,
        portfolio_value=provisional_portfolio_value,
        peak_portfolio_value=peak_value,
        drawdown_pct=_drawdown_pct(peak_value=peak_value, portfolio_value=provisional_portfolio_value),
        max_total_exposure_pct=max_total_exposure_pct,
        max_cluster_exposure_pct=max_cluster_exposure_pct,
        kill_switch_active=kill_switch_active,
        kill_switch_reason=kill_switch_reason,
        evaluated_at_utc=hour_ts_utc,
    )
    portfolio_row = writer.build_portfolio_hourly_state_row(
        run_seed_hash=run_context.run_seed_hash,
        run_mode=normalized_mode,
        account_id=account_id,
        hour_ts_utc=hour_ts_utc,
        source_run_id=run_id,
        cash_balance=cash_balance,
        market_value=market_value,
        peak_portfolio_value=peak_value,
        open_position_count=open_position_count,
        halted=(risk_row.halt_new_entries or risk_row.kill_switch_active),
    )

    cluster_ids = sorted({memberships[asset_id] for asset_id in required_assets})
    cluster_rows = tuple(
        writer.build_cluster_exposure_hourly_state_row(
            run_seed_hash=run_context.run_seed_hash,
            run_mode=normalized_mode,
            account_id=account_id,
            cluster_id=cluster_id,
            hour_ts_utc=hour_ts_utc,
            source_run_id=run_id,
            gross_exposure_notional=cluster_notional.get(cluster_id, Decimal("0").quantize(NUMERIC_18)),
            portfolio_value=portfolio_row.portfolio_value,
            max_cluster_exposure_pct=risk_row.max_cluster_exposure_pct,
            parent_risk_hash=risk_row.row_hash,
        )
        for cluster_id in cluster_ids
    )

    return _Phase5HourlyStateResult(
        portfolio_row=portfolio_row,
        risk_row=risk_row,
        cluster_rows=cluster_rows,
    )


def _ensure_phase5_hourly_state(
    db: RuntimeDatabase,
    builder: DeterministicContextBuilder,
    writer: AppendOnlyRuntimeWriter,
    run_id: UUID,
    account_id: int,
    run_mode: str,
    hour_ts_utc: datetime,
) -> _Phase5HourlyStateResult:
    expected = _build_expected_phase5_hourly_state(
        db=db,
        builder=builder,
        writer=writer,
        run_id=run_id,
        account_id=account_id,
        run_mode=run_mode,
        hour_ts_utc=hour_ts_utc,
    )

    existing_portfolio = db.fetch_one(
        """
        SELECT row_hash
        FROM portfolio_hourly_state
        WHERE run_mode = :run_mode
          AND account_id = :account_id
          AND hour_ts_utc = :hour_ts_utc
        """,
        {"run_mode": run_mode.upper(), "account_id": account_id, "hour_ts_utc": hour_ts_utc},
    )
    if existing_portfolio is None:
        writer.insert_portfolio_hourly_state(expected.portfolio_row)
    elif str(existing_portfolio["row_hash"]) != expected.portfolio_row.row_hash:
        raise DeterministicAbortError("portfolio_hourly_state hash mismatch for execution hour.")

    existing_risk = db.fetch_one(
        """
        SELECT row_hash
        FROM risk_hourly_state
        WHERE run_mode = :run_mode
          AND account_id = :account_id
          AND hour_ts_utc = :hour_ts_utc
          AND source_run_id = :source_run_id
        """,
        {
            "run_mode": run_mode.upper(),
            "account_id": account_id,
            "hour_ts_utc": hour_ts_utc,
            "source_run_id": str(run_id),
        },
    )
    if existing_risk is None:
        writer.insert_risk_hourly_state(expected.risk_row)
    elif str(existing_risk["row_hash"]) != expected.risk_row.row_hash:
        raise DeterministicAbortError("risk_hourly_state hash mismatch for execution hour.")

    stored_clusters = db.fetch_all(
        """
        SELECT cluster_id, row_hash
        FROM cluster_exposure_hourly_state
        WHERE run_mode = :run_mode
          AND account_id = :account_id
          AND hour_ts_utc = :hour_ts_utc
          AND source_run_id = :source_run_id
        ORDER BY cluster_id ASC
        """,
        {
            "run_mode": run_mode.upper(),
            "account_id": account_id,
            "hour_ts_utc": hour_ts_utc,
            "source_run_id": str(run_id),
        },
    )
    expected_clusters = {row.cluster_id: row for row in expected.cluster_rows}
    stored_cluster_map = {int(row["cluster_id"]): row for row in stored_clusters}

    for cluster_id in sorted(stored_cluster_map):
        if cluster_id not in expected_clusters:
            raise DeterministicAbortError(
                f"cluster_exposure_hourly_state contains unexpected cluster_id={cluster_id} for hour."
            )

    for cluster_id, expected_row in expected_clusters.items():
        stored_row = stored_cluster_map.get(cluster_id)
        if stored_row is None:
            writer.insert_cluster_exposure_hourly_state(expected_row)
            continue
        if str(stored_row["row_hash"]) != expected_row.row_hash:
            raise DeterministicAbortError(
                f"cluster_exposure_hourly_state hash mismatch for cluster_id={cluster_id}."
            )

    return expected


def _resolve_starting_cash_balance(
    *,
    builder: DeterministicContextBuilder,
    run_context: RunContextState,
    run_mode: str,
    prior_ledger: Optional[PriorEconomicState],
    prior_portfolio: Any,
) -> Decimal:
    if prior_ledger is not None:
        return normalize_decimal(prior_ledger.balance_after, NUMERIC_18)
    if run_mode == "BACKTEST":
        if run_context.backtest_run_id is None:
            raise DeterministicAbortError("BACKTEST run_context missing backtest_run_id.")
        return normalize_decimal(
            builder.load_backtest_initial_capital(run_context.backtest_run_id),
            NUMERIC_18,
        )
    if prior_portfolio is not None:
        return normalize_decimal(prior_portfolio.cash_balance, NUMERIC_18)
    raise DeterministicAbortError(
        f"{run_mode} requires prior portfolio/ledger bootstrap when no prior ledger exists."
    )


def _drawdown_pct(*, peak_value: Decimal, portfolio_value: Decimal) -> Decimal:
    if peak_value <= 0:
        return Decimal("0").quantize(NUMERIC_10)
    return normalize_decimal((peak_value - portfolio_value) / peak_value, NUMERIC_10)


def _load_active_memberships(
    db: RuntimeDatabase,
    asset_ids: Sequence[int],
    hour_ts_utc: datetime,
) -> dict[int, int]:
    if not asset_ids:
        return {}
    rows = db.fetch_all(
        """
        SELECT asset_id, cluster_id, effective_from_utc
        FROM asset_cluster_membership
        WHERE effective_from_utc <= :hour_ts_utc
          AND (effective_to_utc IS NULL OR effective_to_utc > :hour_ts_utc)
        ORDER BY asset_id ASC, effective_from_utc DESC, membership_id DESC
        """,
        {"hour_ts_utc": hour_ts_utc},
    )
    target = set(asset_ids)
    by_asset: dict[int, int] = {}
    for row in rows:
        asset_id = int(row["asset_id"])
        if asset_id not in target or asset_id in by_asset:
            continue
        by_asset[asset_id] = int(row["cluster_id"])
    missing = sorted(target - set(by_asset))
    if missing:
        raise DeterministicAbortError(f"Missing cluster membership for assets={missing}.")
    return by_asset


def _resolve_mark_price(
    *,
    db: RuntimeDatabase,
    account_id: int,
    run_mode: str,
    asset_id: int,
    hour_ts_utc: datetime,
) -> Optional[Decimal]:
    snapshot = db.fetch_one(
        """
        SELECT best_bid_price, best_ask_price
        FROM order_book_snapshot
        WHERE asset_id = :asset_id
          AND snapshot_ts_utc <= :hour_ts_utc
        ORDER BY snapshot_ts_utc DESC, row_hash DESC
        LIMIT 1
        """,
        {"asset_id": asset_id, "hour_ts_utc": hour_ts_utc},
    )
    if snapshot is not None:
        bid = _to_decimal(snapshot["best_bid_price"])
        ask = _to_decimal(snapshot["best_ask_price"])
        if bid > 0 and ask > 0:
            midpoint = normalize_decimal((bid + ask) / Decimal("2"), NUMERIC_18)
            return midpoint

    ohlcv = db.fetch_one(
        """
        SELECT close_price
        FROM market_ohlcv_hourly
        WHERE asset_id = :asset_id
          AND hour_ts_utc <= :hour_ts_utc
        ORDER BY hour_ts_utc DESC, source_venue ASC, row_hash ASC
        LIMIT 1
        """,
        {"asset_id": asset_id, "hour_ts_utc": hour_ts_utc},
    )
    if ohlcv is not None:
        close_price = _to_decimal(ohlcv["close_price"])
        if close_price > 0:
            return normalize_decimal(close_price, NUMERIC_18)

    historical_fill = db.fetch_one(
        """
        SELECT fill_price
        FROM order_fill
        WHERE account_id = :account_id
          AND run_mode = :run_mode
          AND asset_id = :asset_id
          AND fill_ts_utc < :hour_ts_utc
        ORDER BY fill_ts_utc DESC, fill_id DESC
        LIMIT 1
        """,
        {
            "account_id": account_id,
            "run_mode": run_mode,
            "asset_id": asset_id,
            "hour_ts_utc": hour_ts_utc,
        },
    )
    if historical_fill is not None:
        fill_price = _to_decimal(historical_fill["fill_price"])
        if fill_price > 0:
            return normalize_decimal(fill_price, NUMERIC_18)
    return None


def _build_expected_cash_ledger_rows(
    *,
    writer: AppendOnlyRuntimeWriter,
    context: ExecutionContext,
    order_requests: Sequence[OrderRequestRow],
    order_fills: Sequence[OrderFillRow],
    prior_ledger_state: Optional[PriorEconomicState],
) -> tuple[CashLedgerRow, ...]:
    order_side_by_id = {row.order_id: row.side for row in order_requests}
    seq = (prior_ledger_state.ledger_seq + 1) if prior_ledger_state is not None else 1
    prev_hash = prior_ledger_state.ledger_hash if prior_ledger_state is not None else None
    if prior_ledger_state is not None:
        balance_before = normalize_decimal(prior_ledger_state.balance_after, NUMERIC_18)
    else:
        balance_before = normalize_decimal(context.capital_state.cash_balance, NUMERIC_18)

    rows: list[CashLedgerRow] = []
    sorted_fills = sorted(order_fills, key=lambda item: (item.fill_ts_utc, str(item.fill_id)))
    for fill in sorted_fills:
        side = order_side_by_id.get(fill.order_id)
        if side is None:
            raise DeterministicAbortError(
                f"Missing order_request side for order_fill order_id={fill.order_id}."
            )
        row = writer.build_cash_ledger_row(
            context=context,
            fill=fill,
            order_side=side,
            ledger_seq=seq,
            balance_before=balance_before,
            prev_ledger_hash=prev_hash,
        )
        rows.append(row)
        seq += 1
        prev_hash = row.ledger_hash
        balance_before = row.balance_after
    return tuple(rows)


def _ensure_phase5_cash_ledger_rows(
    *,
    db: RuntimeDatabase,
    writer: AppendOnlyRuntimeWriter,
    context: ExecutionContext,
    order_requests: Sequence[OrderRequestRow],
    order_fills: Sequence[OrderFillRow],
    prior_ledger_state: Optional[PriorEconomicState],
) -> tuple[CashLedgerRow, ...]:
    expected_rows = _build_expected_cash_ledger_rows(
        writer=writer,
        context=context,
        order_requests=order_requests,
        order_fills=order_fills,
        prior_ledger_state=prior_ledger_state,
    )
    stored_rows = db.fetch_all(
        """
        SELECT ledger_seq, row_hash
        FROM cash_ledger
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :origin_hour_ts_utc
        ORDER BY ledger_seq ASC
        """,
        {
            "run_id": str(context.run_context.run_id),
            "account_id": context.run_context.account_id,
            "origin_hour_ts_utc": context.run_context.origin_hour_ts_utc,
        },
    )

    expected_by_seq = {row.ledger_seq: row for row in expected_rows}
    stored_by_seq = {int(row["ledger_seq"]): row for row in stored_rows}

    for seq in sorted(stored_by_seq):
        if seq not in expected_by_seq:
            raise DeterministicAbortError(f"cash_ledger contains unexpected ledger_seq={seq}.")
        if str(stored_by_seq[seq]["row_hash"]) != expected_by_seq[seq].row_hash:
            raise DeterministicAbortError(f"cash_ledger hash mismatch for ledger_seq={seq}.")

    for row in expected_rows:
        if row.ledger_seq not in stored_by_seq:
            writer.insert_cash_ledger(row)

    return expected_rows


def _plan_runtime_artifacts(
    context: ExecutionContext,
    writer: AppendOnlyRuntimeWriter,
    risk_profile: Optional[RuntimeRiskProfile] = None,
) -> RuntimeWriteResult:
    trade_signals: list[TradeSignalRow] = []
    order_requests: list[OrderRequestRow] = []
    order_fills: list[OrderFillRow] = []
    position_lots: list[PositionLotRow] = []
    executed_trades: list[ExecutedTradeRow] = []
    risk_events: list[RiskEventRow] = []
    emitted_risk_events: set[tuple[str, str, str, str]] = set()

    adapter = DeterministicExchangeSimulator()
    planned_lots_by_asset: dict[int, list[PositionLotRow]] = {}
    planned_fills_by_id: dict[UUID, OrderFillRow] = {}
    planned_lot_consumed_qty: dict[UUID, Decimal] = {}

    for prediction in context.predictions:
        regime = context.find_regime(prediction.asset_id, prediction.model_version_id)
        if regime is None:
            raise DeterministicAbortError(
                f"Missing regime for asset_id={prediction.asset_id} "
                f"model_version_id={prediction.model_version_id}."
            )

        cluster_hash = _cluster_state_hash_for_prediction(context, prediction)
        decision = deterministic_decision(
            prediction_hash=prediction.row_hash,
            regime_hash=regime.row_hash,
            capital_state_hash=context.capital_state.row_hash,
            risk_state_hash=context.risk_state.row_hash,
            cluster_state_hash=cluster_hash,
        )

        adaptive_action_eval = evaluate_adaptive_horizon_action(
            candidate_action=decision.action,
            prediction=prediction,
            context=context,
            risk_profile=risk_profile,
        )
        severe_recovery_eval = evaluate_severe_loss_recovery_action(
            candidate_action=adaptive_action_eval.action,
            prediction=prediction,
            context=context,
            risk_profile=risk_profile,
        )
        sizing_eval = compute_volatility_adjusted_fraction(
            action=severe_recovery_eval.action,
            candidate_fraction=decision.position_size_fraction,
            asset_id=prediction.asset_id,
            context=context,
            risk_profile=risk_profile,
        )
        adjusted_decision = replace(
            decision,
            action=severe_recovery_eval.action,
            direction="LONG" if severe_recovery_eval.action == "ENTER" else "FLAT",
            position_size_fraction=sizing_eval.adjusted_fraction,
        )

        activation = (
            context.find_activation(prediction.activation_id)
            if prediction.activation_id is not None
            else None
        )
        activation_result = enforce_activation_gate(
            run_mode=context.run_context.run_mode,
            hour_ts_utc=context.run_context.origin_hour_ts_utc,
            model_version_id=prediction.model_version_id,
            activation=activation,
        )

        preliminary_signal = writer.build_trade_signal_row(
            context=context,
            prediction=prediction,
            regime=regime,
            decision=adjusted_decision,
            action_override=None,
        )

        violations: list[RiskViolation] = []
        violations.extend(enforce_cross_account_isolation(context))
        if not activation_result.allowed:
            violations.append(
                RiskViolation(
                    event_type="ACTIVATION_GATE",
                    severity="HIGH",
                    reason_code=activation_result.reason_code,
                    detail=activation_result.detail,
                )
            )
        violations.extend(enforce_runtime_risk_gate(preliminary_signal.action, context))
        violations.extend(
            enforce_position_count_cap(
                action=preliminary_signal.action,
                context=context,
                risk_profile=risk_profile,
            )
        )
        violations.extend(
            enforce_severe_loss_entry_gate(
                action=preliminary_signal.action,
                context=context,
                risk_profile=risk_profile,
            )
        )
        if preliminary_signal.action == "ENTER" and preliminary_signal.net_edge <= Decimal("0"):
            violations.append(
                RiskViolation(
                    event_type="RISK_GATE",
                    severity="MEDIUM",
                    reason_code="ENTER_COST_GATE_FAILED",
                    detail="Expected return does not exceed deterministic transaction cost.",
                )
            )
        violations.extend(
            enforce_capital_preservation(
                preliminary_signal.action,
                preliminary_signal.target_position_notional,
                context,
                risk_profile,
            )
        )
        violations.extend(
            enforce_cluster_cap(
                preliminary_signal.action,
                prediction.asset_id,
                preliminary_signal.target_position_notional,
                context,
                risk_profile,
            )
        )

        action_override = "HOLD" if violations else None
        final_signal = writer.build_trade_signal_row(
            context=context,
            prediction=prediction,
            regime=regime,
            decision=adjusted_decision,
            action_override=action_override,
        )
        trade_signals.append(final_signal)

        if not violations:
            intent, intent_events = _derive_order_intent(
                context=context,
                writer=writer,
                signal=final_signal,
                severe_recovery_reason_code=severe_recovery_eval.reason_code,
            )
            risk_events.extend(intent_events)
            if intent is not None:
                attempt_rows, fill_rows, lot_rows, trade_rows, lifecycle_events = _materialize_order_lifecycle(
                    context=context,
                    writer=writer,
                    adapter=adapter,
                    signal=final_signal,
                    intent=intent,
                    planned_lots_by_asset=planned_lots_by_asset,
                    planned_fills_by_id=planned_fills_by_id,
                    planned_lot_consumed_qty=planned_lot_consumed_qty,
                )
                order_requests.extend(attempt_rows)
                order_fills.extend(fill_rows)
                position_lots.extend(lot_rows)
                executed_trades.extend(trade_rows)
                risk_events.extend(lifecycle_events)
        else:
            for violation in violations:
                # De-duplicate semantically identical run-hour violations so
                # repeated asset-level blocks do not collide on deterministic IDs.
                event_key = (
                    violation.event_type,
                    violation.severity,
                    violation.reason_code,
                    violation.detail,
                )
                if event_key in emitted_risk_events:
                    continue
                emitted_risk_events.add(event_key)
                risk_events.append(
                    writer.build_risk_event_row(
                        context=context,
                        event_type=violation.event_type,
                        severity=violation.severity,
                        reason_code=violation.reason_code,
                        detail=violation.detail,
                    )
                )

        risk_state_eval = evaluate_risk_state_machine(context=context, risk_profile=risk_profile)
        if severe_recovery_eval.reason_code != "NO_SEVERE_LOSS_RECOVERY":
            action_reason_code = severe_recovery_eval.reason_code
        elif final_signal.action == "ENTER":
            action_reason_code = sizing_eval.reason_code
        else:
            action_reason_code = adaptive_action_eval.reason_code
        risk_events.append(
            writer.build_risk_event_row(
                context=context,
                event_type="DECISION_TRACE",
                severity="LOW",
                reason_code=action_reason_code,
                detail=(
                    "Decision trace for "
                    f"asset_id={prediction.asset_id} "
                    f"horizon={prediction.horizon} "
                    f"model_version_id={prediction.model_version_id} "
                    f"action={final_signal.action}."
                ),
                details={
                    "profile_version": context.risk_profile.profile_version,
                    "risk_state_mode": risk_state_eval.state,
                    "final_action": final_signal.action,
                    "action_reason_code": action_reason_code,
                    "adaptive_reason_code": adaptive_action_eval.reason_code,
                    "severe_recovery_reason_code": severe_recovery_eval.reason_code,
                    "volatility_reason_code": sizing_eval.reason_code,
                    "base_fraction": str(sizing_eval.base_fraction),
                    "observed_volatility": (
                        str(sizing_eval.observed_volatility)
                        if sizing_eval.observed_volatility is not None
                        else None
                    ),
                    "volatility_scale": str(sizing_eval.volatility_scale),
                    "adjusted_fraction": str(sizing_eval.adjusted_fraction),
                    "derisk_fraction": str(context.risk_profile.derisk_fraction),
                    "violation_reason_codes": [violation.reason_code for violation in violations],
                    "total_exposure_mode": context.risk_profile.total_exposure_mode,
                    "cluster_exposure_mode": context.risk_profile.cluster_exposure_mode,
                    "max_concurrent_positions": context.risk_profile.max_concurrent_positions,
                },
            )
        )

    return RuntimeWriteResult(
        trade_signals=tuple(trade_signals),
        order_requests=tuple(order_requests),
        order_fills=tuple(order_fills),
        position_lots=tuple(position_lots),
        executed_trades=tuple(executed_trades),
        risk_events=tuple(risk_events),
        cash_ledger_rows=tuple(),
        portfolio_hourly_states=tuple(),
        cluster_exposure_hourly_states=tuple(),
        risk_hourly_states=tuple(),
    )


def _derive_order_intent(
    context: ExecutionContext,
    writer: AppendOnlyRuntimeWriter,
    signal: TradeSignalRow,
    severe_recovery_reason_code: str,
) -> tuple[Optional[_OrderIntent], tuple[RiskEventRow, ...]]:
    events: list[RiskEventRow] = []
    asset_precision = context.find_asset_precision(signal.asset_id)
    if asset_precision is None:
        raise DeterministicAbortError(f"Missing asset precision for asset_id={signal.asset_id}.")
    if asset_precision.lot_size <= 0:
        raise DeterministicAbortError(f"Invalid lot_size for asset_id={signal.asset_id}.")

    position = context.find_position(signal.asset_id)
    inventory_qty = (
        normalize_decimal(position.quantity, NUMERIC_18)
        if position is not None
        else Decimal("0").quantize(NUMERIC_18)
    )

    side: Optional[str] = None
    raw_qty: Optional[Decimal] = None
    requested_notional: Optional[Decimal] = None
    source_reason_code = "SIGNAL_ENTER"

    if signal.action == "ENTER" and signal.target_position_notional > 0:
        side = "BUY"
        reference_price = _resolve_signal_reference_price(
            context=context,
            asset_id=signal.asset_id,
            side="BUY",
        )
        if reference_price is None or reference_price <= 0:
            events.append(
                writer.build_risk_event_row(
                    context=context,
                    event_type="ORDER_LIFECYCLE",
                    severity="MEDIUM",
                    reason_code="ORDER_REFERENCE_PRICE_UNAVAILABLE",
                    detail=(
                        f"signal_id={signal.signal_id} has no order-book/ohlcv reference "
                        "price for ENTER sizing."
                    ),
                )
            )
            return None, tuple(events)
        raw_qty = normalize_decimal(signal.target_position_notional / reference_price, NUMERIC_18)
        requested_notional = normalize_decimal(signal.target_position_notional, NUMERIC_18)
    elif signal.action == "EXIT":
        side = "SELL"
        source_reason_code = "SIGNAL_EXIT"
        if inventory_qty <= 0:
            events.append(
                writer.build_risk_event_row(
                    context=context,
                    event_type="ORDER_LIFECYCLE",
                    severity="MEDIUM",
                    reason_code="NO_INVENTORY_FOR_SELL",
                    detail=f"signal_id={signal.signal_id} has zero inventory for SELL intent.",
                )
            )
            return None, tuple(events)
        raw_qty = inventory_qty
        requested_notional = raw_qty
    elif signal.action == "HOLD" and severe_recovery_reason_code == "SEVERE_RECOVERY_DERISK_INTENT":
        side = "SELL"
        source_reason_code = severe_recovery_reason_code
        if inventory_qty <= 0:
            events.append(
                writer.build_risk_event_row(
                    context=context,
                    event_type="ORDER_LIFECYCLE",
                    severity="MEDIUM",
                    reason_code="NO_INVENTORY_FOR_SELL",
                    detail=f"signal_id={signal.signal_id} has zero inventory for de-risk SELL intent.",
                )
            )
            return None, tuple(events)
        raw_qty = normalize_decimal(inventory_qty * context.risk_profile.derisk_fraction, NUMERIC_18)
        requested_notional = raw_qty
    else:
        return None, tuple(events)

    if side == "SELL" and raw_qty > inventory_qty:
        events.append(
            writer.build_risk_event_row(
                context=context,
                event_type="ORDER_LIFECYCLE",
                severity="LOW",
                reason_code="SELL_QTY_CLIPPED_TO_INVENTORY",
                detail=(
                    f"signal_id={signal.signal_id} clipped sell qty from {raw_qty} "
                    f"to inventory {inventory_qty}."
                ),
            )
        )
        raw_qty = inventory_qty

    normalized_qty = _round_down_to_lot_size(raw_qty, asset_precision.lot_size)
    if normalized_qty <= 0:
        events.append(
            writer.build_risk_event_row(
                context=context,
                event_type="ORDER_LIFECYCLE",
                severity="MEDIUM",
                reason_code="ORDER_QTY_BELOW_LOT_SIZE",
                detail=(
                    f"signal_id={signal.signal_id} normalized qty={normalized_qty} "
                    f"at lot_size={asset_precision.lot_size}."
                ),
            )
        )
        return None, tuple(events)

    if side == "SELL" and source_reason_code == "SEVERE_RECOVERY_DERISK_INTENT":
        events.append(
            writer.build_risk_event_row(
                context=context,
                event_type="ORDER_LIFECYCLE",
                severity="LOW",
                reason_code="SEVERE_RECOVERY_DERISK_ORDER_EMITTED",
                detail=(
                    f"signal_id={signal.signal_id} emitted de-risk SELL qty={normalized_qty} "
                    f"fraction={context.risk_profile.derisk_fraction}."
                ),
            )
        )

    assert requested_notional is not None
    requested_notional = normalize_decimal(max(requested_notional, NUMERIC_18), NUMERIC_18)

    return (
        _OrderIntent(
            side=side,
            requested_qty=normalized_qty,
            requested_notional=requested_notional,
            source_reason_code=source_reason_code,
        ),
        tuple(events),
    )


def _materialize_order_lifecycle(
    context: ExecutionContext,
    writer: AppendOnlyRuntimeWriter,
    adapter: DeterministicExchangeSimulator,
    signal: TradeSignalRow,
    intent: _OrderIntent,
    planned_lots_by_asset: dict[int, list[PositionLotRow]],
    planned_fills_by_id: dict[UUID, OrderFillRow],
    planned_lot_consumed_qty: dict[UUID, Decimal],
) -> tuple[
    tuple[OrderRequestRow, ...],
    tuple[OrderFillRow, ...],
    tuple[PositionLotRow, ...],
    tuple[ExecutedTradeRow, ...],
    tuple[RiskEventRow, ...],
]:
    order_attempts: list[OrderRequestRow] = []
    fill_rows: list[OrderFillRow] = []
    lot_rows: list[PositionLotRow] = []
    trade_rows: list[ExecutedTradeRow] = []
    lifecycle_events: list[RiskEventRow] = []

    remaining_qty = normalize_decimal(intent.requested_qty, NUMERIC_18)
    attempt_ts = _attempt_timestamps(context.run_context.origin_hour_ts_utc)

    for attempt_seq, ts in enumerate(attempt_ts):
        if remaining_qty <= 0:
            break

        request = OrderAttemptRequest(
            asset_id=signal.asset_id,
            side=intent.side,
            requested_qty=remaining_qty,
            attempt_ts_utc=ts,
        )
        attempt_result = adapter.simulate_attempt(context, request)

        filled_qty = normalize_decimal(min(remaining_qty, attempt_result.filled_qty), NUMERIC_18)
        if attempt_result.fill_price is None or attempt_result.reference_price is None:
            filled_qty = Decimal("0").quantize(NUMERIC_18)
            lifecycle_events.append(
                writer.build_risk_event_row(
                    context=context,
                    event_type="ORDER_LIFECYCLE",
                    severity="HIGH",
                    reason_code="ORDER_PRICE_UNAVAILABLE",
                    detail=(
                        f"signal_id={signal.signal_id} attempt_seq={attempt_seq} has no deterministic "
                        "price source."
                    ),
                )
            )

        if filled_qty >= remaining_qty:
            status = "FILLED"
            filled_qty = remaining_qty
        elif filled_qty > 0:
            status = "PARTIAL"
        else:
            status = "CANCELLED"

        requested_notional = _attempt_requested_notional(intent=intent, requested_qty=remaining_qty)
        order = writer.build_order_request_attempt_row(
            context=context,
            signal=signal,
            side=intent.side,
            request_ts_utc=ts,
            requested_qty=remaining_qty,
            requested_notional=requested_notional,
            status=status,
            attempt_seq=attempt_seq,
        )
        order_attempts.append(order)

        if filled_qty > 0 and attempt_result.fill_price is not None:
            fill = writer.build_order_fill_row(
                context=context,
                order=order,
                fill_ts_utc=ts,
                fill_price=attempt_result.fill_price,
                fill_qty=filled_qty,
                liquidity_flag=attempt_result.liquidity_flag,
                attempt_seq=attempt_seq,
            )
            fill_rows.append(fill)
            planned_fills_by_id[fill.fill_id] = fill

            if intent.side == "BUY":
                lot = writer.build_position_lot_row(context=context, fill=fill)
                lot_rows.append(lot)
                planned_lots_by_asset.setdefault(lot.asset_id, []).append(lot)
            else:
                sell_residual = _allocate_sell_fill_fifo(
                    context=context,
                    writer=writer,
                    fill=fill,
                    planned_lots_by_asset=planned_lots_by_asset,
                    planned_fills_by_id=planned_fills_by_id,
                    planned_lot_consumed_qty=planned_lot_consumed_qty,
                    trade_rows=trade_rows,
                )
                if sell_residual > 0:
                    lifecycle_events.append(
                        writer.build_risk_event_row(
                            context=context,
                            event_type="ORDER_LIFECYCLE",
                            severity="HIGH",
                            reason_code="SELL_ALLOCATION_INSUFFICIENT_LOTS",
                            detail=(
                                f"fill_id={fill.fill_id} residual_qty={sell_residual} could not be "
                                "allocated via FIFO lots."
                            ),
                        )
                    )

        remaining_qty = normalize_decimal(remaining_qty - filled_qty, NUMERIC_18)

    if remaining_qty > 0:
        lifecycle_events.append(
            writer.build_risk_event_row(
                context=context,
                event_type="ORDER_LIFECYCLE",
                severity="MEDIUM",
                reason_code="ORDER_RETRY_EXHAUSTED",
                detail=(
                    f"signal_id={signal.signal_id} remaining_qty={remaining_qty} after "
                    f"{len(attempt_ts)} deterministic attempts."
                ),
            )
        )

    return (
        tuple(order_attempts),
        tuple(fill_rows),
        tuple(lot_rows),
        tuple(trade_rows),
        tuple(lifecycle_events),
    )


def _allocate_sell_fill_fifo(
    context: ExecutionContext,
    writer: AppendOnlyRuntimeWriter,
    fill: OrderFillRow,
    planned_lots_by_asset: Mapping[int, Sequence[PositionLotRow]],
    planned_fills_by_id: Mapping[UUID, OrderFillRow],
    planned_lot_consumed_qty: dict[UUID, Decimal],
    trade_rows: list[ExecutedTradeRow],
) -> Decimal:
    remaining = normalize_decimal(fill.fill_qty, NUMERIC_18)
    lot_views = _build_fifo_lot_views_for_asset(
        context=context,
        asset_id=fill.asset_id,
        planned_lots_by_asset=planned_lots_by_asset,
        planned_fills_by_id=planned_fills_by_id,
    )
    for lot_view in lot_views:
        if remaining <= 0:
            break
        planned_consumed = planned_lot_consumed_qty.get(lot_view.lot_id, Decimal("0").quantize(NUMERIC_18))
        available = normalize_decimal(
            lot_view.open_qty - lot_view.historical_consumed_qty - planned_consumed,
            NUMERIC_18,
        )
        if available <= 0:
            continue
        quantity = normalize_decimal(min(available, remaining), NUMERIC_18)
        trade = writer.build_executed_trade_row(
            context=context,
            lot_id=lot_view.lot_id,
            lot_asset_id=lot_view.asset_id,
            entry_ts_utc=lot_view.open_ts_utc,
            entry_price=lot_view.open_price,
            lot_open_qty=lot_view.open_qty,
            lot_open_fee=lot_view.open_fee,
            entry_fill_slippage_cost=lot_view.open_slippage_cost,
            parent_lot_hash=lot_view.parent_lot_hash,
            exit_fill=fill,
            quantity=quantity,
        )
        trade_rows.append(trade)
        planned_lot_consumed_qty[lot_view.lot_id] = normalize_decimal(planned_consumed + quantity, NUMERIC_18)
        remaining = normalize_decimal(remaining - quantity, NUMERIC_18)
    return remaining


def _build_fifo_lot_views_for_asset(
    context: ExecutionContext,
    asset_id: int,
    planned_lots_by_asset: Mapping[int, Sequence[PositionLotRow]],
    planned_fills_by_id: Mapping[UUID, OrderFillRow],
) -> tuple[_LotView, ...]:
    views: list[_LotView] = []
    for lot in context.lots_for_asset(asset_id):
        open_fill = context.find_existing_fill(lot.open_fill_id)
        if open_fill is None:
            raise DeterministicAbortError(f"Missing open_fill_id={lot.open_fill_id} for lot_id={lot.lot_id}.")
        views.append(
            _LotView(
                lot_id=lot.lot_id,
                asset_id=lot.asset_id,
                open_ts_utc=lot.open_ts_utc,
                open_price=lot.open_price,
                open_qty=lot.open_qty,
                open_fee=lot.open_fee,
                open_slippage_cost=open_fill.slippage_cost,
                parent_lot_hash=lot.row_hash,
                historical_consumed_qty=normalize_decimal(context.executed_qty_for_lot(lot.lot_id), NUMERIC_18),
            )
        )
    for lot in planned_lots_by_asset.get(asset_id, ()):
        open_fill = planned_fills_by_id.get(lot.open_fill_id)
        if open_fill is None:
            raise DeterministicAbortError(f"Missing planned fill for open_fill_id={lot.open_fill_id}.")
        views.append(
            _LotView(
                lot_id=lot.lot_id,
                asset_id=lot.asset_id,
                open_ts_utc=lot.open_ts_utc,
                open_price=lot.open_price,
                open_qty=lot.open_qty,
                open_fee=lot.open_fee,
                open_slippage_cost=open_fill.slippage_cost,
                parent_lot_hash=lot.row_hash,
                historical_consumed_qty=Decimal("0").quantize(NUMERIC_18),
            )
        )
    views.sort(key=lambda item: (item.open_ts_utc, str(item.lot_id)))
    return tuple(views)


def _attempt_timestamps(origin_hour_ts_utc: datetime) -> tuple[datetime, ...]:
    ts = [origin_hour_ts_utc]
    current = origin_hour_ts_utc
    for backoff_minutes in _RETRY_BACKOFF_MINUTES:
        current = current + timedelta(minutes=backoff_minutes)
        ts.append(current)
    return tuple(ts)


def _attempt_requested_notional(intent: _OrderIntent, requested_qty: Decimal) -> Decimal:
    if requested_qty <= 0:
        raise DeterministicAbortError("requested_qty must be positive when deriving requested_notional.")

    if intent.side == "SELL":
        return normalize_decimal(requested_qty, NUMERIC_18)

    ratio = normalize_decimal(requested_qty / intent.requested_qty, NUMERIC_18)
    notional = normalize_decimal(intent.requested_notional * ratio, NUMERIC_18)
    if notional <= 0:
        notional = normalize_decimal(requested_qty, NUMERIC_18)
    return notional


def _resolve_signal_reference_price(
    *,
    context: ExecutionContext,
    asset_id: int,
    side: str,
) -> Optional[Decimal]:
    snapshot = context.find_latest_order_book_snapshot(
        asset_id=asset_id,
        as_of_ts_utc=context.run_context.origin_hour_ts_utc,
    )
    if snapshot is not None:
        if side == "BUY":
            ask = normalize_decimal(snapshot.best_ask_price, NUMERIC_18)
            if ask > 0:
                return ask
        else:
            bid = normalize_decimal(snapshot.best_bid_price, NUMERIC_18)
            if bid > 0:
                return bid

    candle = context.find_ohlcv(asset_id)
    if candle is not None:
        close = normalize_decimal(candle.close_price, NUMERIC_18)
        if close > 0:
            return close
    return None


def _round_down_to_lot_size(raw_qty: Decimal, lot_size: Decimal) -> Decimal:
    if raw_qty <= 0:
        return Decimal("0").quantize(NUMERIC_18)
    if lot_size <= 0:
        raise DeterministicAbortError("lot_size must be positive.")
    lot_steps = (raw_qty / lot_size).to_integral_value(rounding=ROUND_DOWN)
    normalized_qty = lot_steps * lot_size
    if normalized_qty <= 0:
        return Decimal("0").quantize(NUMERIC_18)
    return normalize_decimal(normalized_qty, NUMERIC_18)


def _cluster_state_hash_for_prediction(context: ExecutionContext, prediction: PredictionState) -> str:
    membership = context.find_membership(prediction.asset_id)
    if membership is None:
        raise DeterministicAbortError(f"Missing cluster membership for asset_id={prediction.asset_id}.")
    cluster_state = context.find_cluster_state(membership.cluster_id)
    if cluster_state is None:
        raise DeterministicAbortError(f"Missing cluster state for cluster_id={membership.cluster_id}.")
    return stable_hash(
        (
            context.run_context.run_seed_hash,
            membership.membership_hash,
            cluster_state.state_hash,
            cluster_state.parent_risk_hash,
            cluster_state.row_hash,
        )
    )


def _compare_signals(
    expected: Sequence[TradeSignalRow],
    stored: Sequence[Mapping[str, Any]],
) -> list[ReplayMismatch]:
    mismatches: list[ReplayMismatch] = []
    expected_map = {str(row.signal_id): row for row in expected}
    stored_map = {str(row["signal_id"]): row for row in stored}

    all_keys = sorted(set(expected_map.keys()) | set(stored_map.keys()))
    for key in all_keys:
        if key not in expected_map:
            mismatches.append(
                ReplayMismatch("trade_signal", key, "presence", "expected_absent", "stored_present")
            )
            continue
        if key not in stored_map:
            mismatches.append(
                ReplayMismatch("trade_signal", key, "presence", "expected_present", "stored_absent")
            )
            continue
        expected_row = expected_map[key]
        stored_row = stored_map[key]
        if str(stored_row["decision_hash"]) != expected_row.decision_hash:
            mismatches.append(
                ReplayMismatch(
                    "trade_signal",
                    key,
                    "decision_hash",
                    expected_row.decision_hash,
                    str(stored_row["decision_hash"]),
                )
            )
        if str(stored_row["row_hash"]) != expected_row.row_hash:
            mismatches.append(
                ReplayMismatch(
                    "trade_signal",
                    key,
                    "row_hash",
                    expected_row.row_hash,
                    str(stored_row["row_hash"]),
                )
            )
    return mismatches


def _compare_orders(
    expected: Sequence[OrderRequestRow],
    stored: Sequence[Mapping[str, Any]],
) -> list[ReplayMismatch]:
    mismatches: list[ReplayMismatch] = []
    expected_map = {str(row.order_id): row for row in expected}
    stored_map = {str(row["order_id"]): row for row in stored}
    all_keys = sorted(set(expected_map.keys()) | set(stored_map.keys()))
    for key in all_keys:
        if key not in expected_map:
            mismatches.append(
                ReplayMismatch("order_request", key, "presence", "expected_absent", "stored_present")
            )
            continue
        if key not in stored_map:
            mismatches.append(
                ReplayMismatch("order_request", key, "presence", "expected_present", "stored_absent")
            )
            continue
        if str(stored_map[key]["row_hash"]) != expected_map[key].row_hash:
            mismatches.append(
                ReplayMismatch(
                    "order_request",
                    key,
                    "row_hash",
                    expected_map[key].row_hash,
                    str(stored_map[key]["row_hash"]),
                )
            )
    return mismatches


def _compare_fills(
    expected: Sequence[OrderFillRow],
    stored: Sequence[Mapping[str, Any]],
) -> list[ReplayMismatch]:
    mismatches: list[ReplayMismatch] = []
    expected_map = {str(row.fill_id): row for row in expected}
    stored_map = {str(row["fill_id"]): row for row in stored}
    all_keys = sorted(set(expected_map.keys()) | set(stored_map.keys()))
    for key in all_keys:
        if key not in expected_map:
            mismatches.append(
                ReplayMismatch("order_fill", key, "presence", "expected_absent", "stored_present")
            )
            continue
        if key not in stored_map:
            mismatches.append(
                ReplayMismatch("order_fill", key, "presence", "expected_present", "stored_absent")
            )
            continue
        if str(stored_map[key]["row_hash"]) != expected_map[key].row_hash:
            mismatches.append(
                ReplayMismatch(
                    "order_fill",
                    key,
                    "row_hash",
                    expected_map[key].row_hash,
                    str(stored_map[key]["row_hash"]),
                )
            )
    return mismatches


def _compare_lots(
    expected: Sequence[PositionLotRow],
    stored: Sequence[Mapping[str, Any]],
) -> list[ReplayMismatch]:
    mismatches: list[ReplayMismatch] = []
    expected_map = {str(row.lot_id): row for row in expected}
    stored_map = {str(row["lot_id"]): row for row in stored}
    all_keys = sorted(set(expected_map.keys()) | set(stored_map.keys()))
    for key in all_keys:
        if key not in expected_map:
            mismatches.append(
                ReplayMismatch("position_lot", key, "presence", "expected_absent", "stored_present")
            )
            continue
        if key not in stored_map:
            mismatches.append(
                ReplayMismatch("position_lot", key, "presence", "expected_present", "stored_absent")
            )
            continue
        if str(stored_map[key]["row_hash"]) != expected_map[key].row_hash:
            mismatches.append(
                ReplayMismatch(
                    "position_lot",
                    key,
                    "row_hash",
                    expected_map[key].row_hash,
                    str(stored_map[key]["row_hash"]),
                )
            )
    return mismatches


def _compare_trades(
    expected: Sequence[ExecutedTradeRow],
    stored: Sequence[Mapping[str, Any]],
) -> list[ReplayMismatch]:
    mismatches: list[ReplayMismatch] = []
    expected_map = {str(row.trade_id): row for row in expected}
    stored_map = {str(row["trade_id"]): row for row in stored}
    all_keys = sorted(set(expected_map.keys()) | set(stored_map.keys()))
    for key in all_keys:
        if key not in expected_map:
            mismatches.append(
                ReplayMismatch("executed_trade", key, "presence", "expected_absent", "stored_present")
            )
            continue
        if key not in stored_map:
            mismatches.append(
                ReplayMismatch("executed_trade", key, "presence", "expected_present", "stored_absent")
            )
            continue
        if str(stored_map[key]["row_hash"]) != expected_map[key].row_hash:
            mismatches.append(
                ReplayMismatch(
                    "executed_trade",
                    key,
                    "row_hash",
                    expected_map[key].row_hash,
                    str(stored_map[key]["row_hash"]),
                )
            )
    return mismatches


def _compare_risk_events(
    expected: Sequence[RiskEventRow],
    stored: Sequence[Mapping[str, Any]],
) -> list[ReplayMismatch]:
    mismatches: list[ReplayMismatch] = []
    expected_map = {str(row.risk_event_id): row for row in expected}
    stored_map = {str(row["risk_event_id"]): row for row in stored}
    all_keys = sorted(set(expected_map.keys()) | set(stored_map.keys()))
    for key in all_keys:
        if key not in expected_map:
            mismatches.append(
                ReplayMismatch("risk_event", key, "presence", "expected_absent", "stored_present")
            )
            continue
        if key not in stored_map:
            mismatches.append(
                ReplayMismatch("risk_event", key, "presence", "expected_present", "stored_absent")
            )
            continue
        if str(stored_map[key]["row_hash"]) != expected_map[key].row_hash:
            mismatches.append(
                ReplayMismatch(
                    "risk_event",
                    key,
                    "row_hash",
                    expected_map[key].row_hash,
                    str(stored_map[key]["row_hash"]),
                )
            )
    return mismatches


def _compare_cash_ledger(
    expected: Sequence[CashLedgerRow],
    stored: Sequence[Mapping[str, Any]],
) -> list[ReplayMismatch]:
    mismatches: list[ReplayMismatch] = []
    expected_map = {str(row.ledger_seq): row for row in expected}
    stored_map = {str(row["ledger_seq"]): row for row in stored}
    all_keys = sorted(set(expected_map.keys()) | set(stored_map.keys()), key=int)
    for key in all_keys:
        if key not in expected_map:
            mismatches.append(
                ReplayMismatch("cash_ledger", key, "presence", "expected_absent", "stored_present")
            )
            continue
        if key not in stored_map:
            mismatches.append(
                ReplayMismatch("cash_ledger", key, "presence", "expected_present", "stored_absent")
            )
            continue
        if str(stored_map[key]["row_hash"]) != expected_map[key].row_hash:
            mismatches.append(
                ReplayMismatch(
                    "cash_ledger",
                    key,
                    "row_hash",
                    expected_map[key].row_hash,
                    str(stored_map[key]["row_hash"]),
                )
            )
    return mismatches


def _compare_portfolio_hourly_states(
    expected: Sequence[PortfolioHourlyStateRow],
    stored: Sequence[Mapping[str, Any]],
) -> list[ReplayMismatch]:
    mismatches: list[ReplayMismatch] = []
    expected_map = {str(row.hour_ts_utc): row for row in expected}
    stored_map = {str(row["hour_ts_utc"]): row for row in stored}
    all_keys = sorted(set(expected_map.keys()) | set(stored_map.keys()))
    for key in all_keys:
        if key not in expected_map:
            mismatches.append(
                ReplayMismatch(
                    "portfolio_hourly_state",
                    key,
                    "presence",
                    "expected_absent",
                    "stored_present",
                )
            )
            continue
        if key not in stored_map:
            mismatches.append(
                ReplayMismatch(
                    "portfolio_hourly_state",
                    key,
                    "presence",
                    "expected_present",
                    "stored_absent",
                )
            )
            continue
        if str(stored_map[key]["row_hash"]) != expected_map[key].row_hash:
            mismatches.append(
                ReplayMismatch(
                    "portfolio_hourly_state",
                    key,
                    "row_hash",
                    expected_map[key].row_hash,
                    str(stored_map[key]["row_hash"]),
                )
            )
    return mismatches


def _compare_cluster_exposure_hourly_states(
    expected: Sequence[ClusterExposureHourlyStateRow],
    stored: Sequence[Mapping[str, Any]],
) -> list[ReplayMismatch]:
    mismatches: list[ReplayMismatch] = []
    expected_map = {str(row.cluster_id): row for row in expected}
    stored_map = {str(row["cluster_id"]): row for row in stored}
    all_keys = sorted(set(expected_map.keys()) | set(stored_map.keys()), key=int)
    for key in all_keys:
        if key not in expected_map:
            mismatches.append(
                ReplayMismatch(
                    "cluster_exposure_hourly_state",
                    key,
                    "presence",
                    "expected_absent",
                    "stored_present",
                )
            )
            continue
        if key not in stored_map:
            mismatches.append(
                ReplayMismatch(
                    "cluster_exposure_hourly_state",
                    key,
                    "presence",
                    "expected_present",
                    "stored_absent",
                )
            )
            continue
        if str(stored_map[key]["row_hash"]) != expected_map[key].row_hash:
            mismatches.append(
                ReplayMismatch(
                    "cluster_exposure_hourly_state",
                    key,
                    "row_hash",
                    expected_map[key].row_hash,
                    str(stored_map[key]["row_hash"]),
                )
            )
    return mismatches


def _compare_risk_hourly_states(
    expected: Sequence[RiskHourlyStateRow],
    stored: Sequence[Mapping[str, Any]],
) -> list[ReplayMismatch]:
    mismatches: list[ReplayMismatch] = []
    expected_map = {str(row.hour_ts_utc): row for row in expected}
    stored_map = {str(row["hour_ts_utc"]): row for row in stored}
    all_keys = sorted(set(expected_map.keys()) | set(stored_map.keys()))
    for key in all_keys:
        if key not in expected_map:
            mismatches.append(
                ReplayMismatch("risk_hourly_state", key, "presence", "expected_absent", "stored_present")
            )
            continue
        if key not in stored_map:
            mismatches.append(
                ReplayMismatch("risk_hourly_state", key, "presence", "expected_present", "stored_absent")
            )
            continue
        if str(stored_map[key]["row_hash"]) != expected_map[key].row_hash:
            mismatches.append(
                ReplayMismatch(
                    "risk_hourly_state",
                    key,
                    "row_hash",
                    expected_map[key].row_hash,
                    str(stored_map[key]["row_hash"]),
                )
            )
    return mismatches
