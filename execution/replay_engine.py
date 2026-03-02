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
    deterministic_decision,
    normalize_decimal,
    stable_hash,
)
from execution.deterministic_context import (
    DeterministicAbortError,
    DeterministicContextBuilder,
    ExecutionContext,
    PredictionState,
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
    ExecutedTradeRow,
    OrderFillRow,
    OrderRequestRow,
    PositionLotRow,
    RiskEventRow,
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
    context = builder.build_context(run_id, account_id, run_mode, hour_ts_utc)
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
            account_id=context.run_context.account_id,
            run_mode=context.run_context.run_mode,
        )
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

        # Preserve and validate ledger continuity after writes.
        writer.assert_ledger_continuity(
            account_id=context.run_context.account_id,
            run_mode=context.run_context.run_mode,
        )

        if tx_started and callable(commit):
            commit()
        return planned
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
    context = builder.build_context(run_id, account_id, run_mode, hour_ts_utc)
    writer = AppendOnlyRuntimeWriter(db)
    expected = _plan_runtime_artifacts(
        context=context,
        writer=writer,
        risk_profile=risk_profile,
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

    mismatches: list[ReplayMismatch] = []
    mismatches.extend(_compare_signals(expected.trade_signals, stored_signals))
    mismatches.extend(_compare_orders(expected.order_requests, stored_orders))
    mismatches.extend(_compare_fills(expected.order_fills, stored_fills))
    mismatches.extend(_compare_lots(expected.position_lots, stored_lots))
    mismatches.extend(_compare_trades(expected.executed_trades, stored_trades))
    mismatches.extend(_compare_risk_events(expected.risk_events, stored_risk_events))

    return ReplayReport(mismatch_count=len(mismatches), mismatches=tuple(mismatches))


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
        raw_qty = normalize_decimal(signal.target_position_notional, NUMERIC_18)
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
