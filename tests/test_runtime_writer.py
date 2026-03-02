"""Unit tests for append-only runtime writer deterministic row construction."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID

import pytest

from execution.decision_engine import DecisionResult, deterministic_decision
from execution.deterministic_context import DeterministicContextBuilder
from execution.runtime_writer import AppendOnlyRuntimeWriter


class _FakeDB:
    def __init__(self) -> None:
        run_id = UUID("11111111-1111-4111-8111-111111111111")
        hour = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.data: dict[str, list[dict[str, Any]]] = {
            "run_context": [
                {
                    "run_id": run_id,
                    "account_id": 1,
                    "run_mode": "LIVE",
                    "hour_ts_utc": hour,
                    "origin_hour_ts_utc": hour,
                    "run_seed_hash": "a" * 64,
                    "context_hash": "b" * 64,
                    "replay_root_hash": "c" * 64,
                }
            ],
            "model_prediction": [
                {
                    "run_id": run_id,
                    "account_id": 1,
                    "run_mode": "LIVE",
                    "asset_id": 1,
                    "hour_ts_utc": hour,
                    "horizon": "H1",
                    "model_version_id": 10,
                    "prob_up": Decimal("0.6500000000"),
                    "expected_return": Decimal("0.020000000000000000"),
                    "upstream_hash": "d" * 64,
                    "row_hash": "5" * 64,
                    "training_window_id": None,
                    "lineage_backtest_run_id": None,
                    "lineage_fold_index": None,
                    "lineage_horizon": None,
                    "activation_id": 11,
                }
            ],
            "regime_output": [
                {
                    "run_id": run_id,
                    "account_id": 1,
                    "run_mode": "LIVE",
                    "asset_id": 1,
                    "hour_ts_utc": hour,
                    "model_version_id": 10,
                    "regime_label": "TRENDING",
                    "upstream_hash": "e" * 64,
                    "row_hash": "1" * 64,
                    "training_window_id": None,
                    "lineage_backtest_run_id": None,
                    "lineage_fold_index": None,
                    "lineage_horizon": None,
                    "activation_id": 11,
                }
            ],
            "risk_hourly_state": [
                {
                    "run_mode": "LIVE",
                    "account_id": 1,
                    "hour_ts_utc": hour,
                    "source_run_id": run_id,
                    "portfolio_value": Decimal("10000"),
                    "base_risk_fraction": Decimal("0.0200000000"),
                    "max_total_exposure_pct": Decimal("0.2"),
                    "max_cluster_exposure_pct": Decimal("0.08"),
                    "halt_new_entries": False,
                    "kill_switch_active": False,
                    "state_hash": "f" * 64,
                    "row_hash": "r" * 64,
                }
            ],
            "portfolio_hourly_state": [
                {
                    "run_mode": "LIVE",
                    "account_id": 1,
                    "hour_ts_utc": hour,
                    "source_run_id": run_id,
                    "cash_balance": Decimal("10000"),
                    "portfolio_value": Decimal("10000"),
                    "total_exposure_pct": Decimal("0.01"),
                    "open_position_count": 1,
                    "row_hash": "g" * 64,
                }
            ],
            "cluster_exposure_hourly_state": [
                {
                    "run_mode": "LIVE",
                    "account_id": 1,
                    "cluster_id": 7,
                    "hour_ts_utc": hour,
                    "source_run_id": run_id,
                    "exposure_pct": Decimal("0.01"),
                    "max_cluster_exposure_pct": Decimal("0.08"),
                    "state_hash": "h" * 64,
                    "parent_risk_hash": "r" * 64,
                    "row_hash": "i" * 64,
                }
            ],
            "position_hourly_state": [
                {
                    "run_mode": "LIVE",
                    "account_id": 1,
                    "asset_id": 1,
                    "hour_ts_utc": hour,
                    "source_run_id": run_id,
                    "quantity": Decimal("1.000000000000000000"),
                    "exposure_pct": Decimal("0.0100000000"),
                    "unrealized_pnl": Decimal("0"),
                    "row_hash": "p" * 64,
                }
            ],
            "model_activation_gate": [
                {
                    "activation_id": 11,
                    "model_version_id": 10,
                    "run_mode": "LIVE",
                    "validation_window_end_utc": hour - timedelta(hours=1),
                    "status": "APPROVED",
                    "approval_hash": "j" * 64,
                }
            ],
            "asset_cluster_membership": [
                {
                    "membership_id": 700,
                    "asset_id": 1,
                    "cluster_id": 7,
                    "membership_hash": "k" * 64,
                    "effective_from_utc": hour - timedelta(days=1),
                }
            ],
            "cost_profile": [
                {
                    "cost_profile_id": 2,
                    "fee_rate": Decimal("0.004"),
                    "slippage_param_hash": "a" * 64,
                }
            ],
            "risk_profile": [
                {
                    "profile_version": "default_v1",
                    "total_exposure_mode": "PERCENT_OF_PV",
                    "max_total_exposure_pct": Decimal("0.2000000000"),
                    "max_total_exposure_amount": None,
                    "cluster_exposure_mode": "PERCENT_OF_PV",
                    "max_cluster_exposure_pct": Decimal("0.0800000000"),
                    "max_cluster_exposure_amount": None,
                    "max_concurrent_positions": 10,
                    "severe_loss_drawdown_trigger": Decimal("0.2000000000"),
                    "volatility_feature_id": 9001,
                    "volatility_target": Decimal("0.0200000000"),
                    "volatility_scale_floor": Decimal("0.5000000000"),
                    "volatility_scale_ceiling": Decimal("1.5000000000"),
                    "hold_min_expected_return": Decimal("0"),
                    "exit_expected_return_threshold": Decimal("-0.005000000000000000"),
                    "recovery_hold_prob_up_threshold": Decimal("0.6000000000"),
                    "recovery_exit_prob_up_threshold": Decimal("0.3500000000"),
                    "derisk_fraction": Decimal("0.5000000000"),
                    "signal_persistence_required": 1,
                    "row_hash": "u" * 64,
                }
            ],
            "account_risk_profile_assignment": [
                {
                    "assignment_id": 1,
                    "profile_version": "default_v1",
                    "account_id": 1,
                    "effective_from_utc": hour - timedelta(days=1),
                    "effective_to_utc": None,
                    "row_hash": "v" * 64,
                }
            ],
            "feature_snapshot": [
                {
                    "asset_id": 1,
                    "feature_id": 9001,
                    "feature_value": Decimal("0.0200000000"),
                    "row_hash": "w" * 64,
                }
            ],
            "asset": [
                {
                    "asset_id": 1,
                    "tick_size": Decimal("0.000000010000000000"),
                    "lot_size": Decimal("0.000000010000000000"),
                }
            ],
            "order_book_snapshot": [],
            "market_ohlcv_hourly": [],
            "order_fill": [],
            "position_lot": [],
            "executed_trade": [],
            "cash_ledger": [],
            "model_training_window": [],
        }
        self.executed: list[tuple[str, Mapping[str, Any]]] = []
        self.ledger_violations = 0

    def fetch_one(self, sql: str, params: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        rows = self.fetch_all(sql, params)
        return rows[0] if rows else None

    def fetch_all(self, sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        q = " ".join(sql.lower().split())
        if "with ordered as" in q and "from cash_ledger" in q:
            return [{"violations": self.ledger_violations}]
        if "from run_context" in q:
            return list(self.data["run_context"])
        if "from model_prediction" in q:
            return list(self.data["model_prediction"])
        if "from regime_output" in q:
            return list(self.data["regime_output"])
        if "from risk_hourly_state" in q:
            return list(self.data["risk_hourly_state"])
        if "from portfolio_hourly_state" in q:
            return list(self.data["portfolio_hourly_state"])
        if "from cluster_exposure_hourly_state" in q:
            return list(self.data["cluster_exposure_hourly_state"])
        if "from model_activation_gate" in q:
            return list(self.data["model_activation_gate"])
        if "from asset_cluster_membership" in q:
            return list(self.data["asset_cluster_membership"])
        if "from cost_profile" in q:
            return list(self.data["cost_profile"])
        if "from account_risk_profile_assignment" in q:
            assignments = list(self.data["account_risk_profile_assignment"])
            profiles = {row["profile_version"]: row for row in self.data["risk_profile"]}
            joined: list[dict[str, Any]] = []
            for assignment in assignments:
                profile = profiles.get(assignment["profile_version"])
                if profile is None:
                    continue
                joined.append({**assignment, **profile})
            return joined
        if "from feature_snapshot" in q:
            return list(self.data["feature_snapshot"])
        if "from position_hourly_state" in q:
            return list(self.data["position_hourly_state"])
        if "from asset" in q:
            return list(self.data["asset"])
        if "from order_book_snapshot" in q:
            return list(self.data["order_book_snapshot"])
        if "from market_ohlcv_hourly" in q:
            return list(self.data["market_ohlcv_hourly"])
        if "from order_fill" in q:
            return list(self.data["order_fill"])
        if "from position_lot" in q:
            return list(self.data["position_lot"])
        if "from executed_trade" in q:
            return list(self.data["executed_trade"])
        if "from cash_ledger" in q:
            return []
        if "from model_training_window" in q:
            return []
        raise RuntimeError(f"Unhandled query: {sql}")

    def execute(self, sql: str, params: Mapping[str, Any]) -> None:
        self.executed.append((sql, params))


def test_writer_builds_deterministic_signal_order_and_event_rows() -> None:
    db = _FakeDB()
    context = DeterministicContextBuilder(db).build_context(
        run_id=db.data["run_context"][0]["run_id"],
        account_id=1,
        run_mode="LIVE",
        hour_ts_utc=db.data["run_context"][0]["origin_hour_ts_utc"],
    )
    prediction = context.predictions[0]
    regime = context.regimes[0]
    decision = deterministic_decision(
        prediction_hash=prediction.row_hash,
        regime_hash=regime.row_hash,
        capital_state_hash=context.capital_state.row_hash,
        risk_state_hash=context.risk_state.row_hash,
        cluster_state_hash=context.cluster_states[0].row_hash,
    )
    writer = AppendOnlyRuntimeWriter(db)
    signal_a = writer.build_trade_signal_row(context, prediction, regime, decision)
    signal_b = writer.build_trade_signal_row(context, prediction, regime, decision)
    assert signal_a.row_hash == signal_b.row_hash

    order = writer.build_order_request_row(context, signal_a)
    if signal_a.action == "ENTER":
        assert order is not None
        assert order.parent_signal_hash == signal_a.row_hash
    else:
        assert order is None

    event_a = writer.build_risk_event_row(
        context=context,
        event_type="RISK_GATE",
        severity="HIGH",
        reason_code="TEST_REASON",
        detail="deterministic detail",
    )
    event_b = writer.build_risk_event_row(
        context=context,
        event_type="RISK_GATE",
        severity="HIGH",
        reason_code="TEST_REASON",
        detail="deterministic detail",
    )
    assert event_a.row_hash == event_b.row_hash


def test_writer_ledger_continuity_violation_aborts() -> None:
    db = _FakeDB()
    db.ledger_violations = 1
    writer = AppendOnlyRuntimeWriter(db)
    with pytest.raises(Exception, match="Cash ledger continuity invariant violated"):
        writer.assert_ledger_continuity(account_id=1, run_mode="LIVE")


def test_writer_invalid_action_override_aborts() -> None:
    db = _FakeDB()
    context = DeterministicContextBuilder(db).build_context(
        run_id=db.data["run_context"][0]["run_id"],
        account_id=1,
        run_mode="LIVE",
        hour_ts_utc=db.data["run_context"][0]["origin_hour_ts_utc"],
    )
    writer = AppendOnlyRuntimeWriter(db)
    decision = deterministic_decision(
        prediction_hash=context.predictions[0].row_hash,
        regime_hash=context.regimes[0].row_hash,
        capital_state_hash=context.capital_state.row_hash,
        risk_state_hash=context.risk_state.row_hash,
        cluster_state_hash=context.cluster_states[0].row_hash,
    )
    with pytest.raises(Exception, match="Invalid signal action"):
        writer.build_trade_signal_row(
            context=context,
            prediction=context.predictions[0],
            regime=context.regimes[0],
            decision=decision,
            action_override="UNKNOWN",
        )


def test_writer_target_notional_is_capped_to_cash() -> None:
    db = _FakeDB()
    db.data["portfolio_hourly_state"][0]["cash_balance"] = Decimal("10")
    context = DeterministicContextBuilder(db).build_context(
        run_id=db.data["run_context"][0]["run_id"],
        account_id=1,
        run_mode="LIVE",
        hour_ts_utc=db.data["run_context"][0]["origin_hour_ts_utc"],
    )
    decision = DecisionResult(
        decision_hash="z" * 64,
        action="ENTER",
        direction="LONG",
        confidence=Decimal("0.5000000000"),
        position_size_fraction=Decimal("0.9000000000"),
    )
    writer = AppendOnlyRuntimeWriter(db)
    signal = writer.build_trade_signal_row(context, context.predictions[0], context.regimes[0], decision)
    assert signal.target_position_notional <= context.capital_state.cash_balance


def test_writer_missing_membership_aborts() -> None:
    db = _FakeDB()
    context = DeterministicContextBuilder(db).build_context(
        run_id=db.data["run_context"][0]["run_id"],
        account_id=1,
        run_mode="LIVE",
        hour_ts_utc=db.data["run_context"][0]["origin_hour_ts_utc"],
    )
    context = replace(context, memberships=tuple())
    decision = deterministic_decision(
        prediction_hash=context.predictions[0].row_hash,
        regime_hash=context.regimes[0].row_hash,
        capital_state_hash=context.capital_state.row_hash,
        risk_state_hash=context.risk_state.row_hash,
        cluster_state_hash=context.cluster_states[0].row_hash,
    )
    writer = AppendOnlyRuntimeWriter(db)
    with pytest.raises(Exception, match="Missing cluster membership"):
        writer.build_trade_signal_row(context, context.predictions[0], context.regimes[0], decision)


def test_writer_missing_cluster_state_aborts() -> None:
    db = _FakeDB()
    db.data["cluster_exposure_hourly_state"] = []
    context = DeterministicContextBuilder(db).build_context(
        run_id=db.data["run_context"][0]["run_id"],
        account_id=1,
        run_mode="LIVE",
        hour_ts_utc=db.data["run_context"][0]["origin_hour_ts_utc"],
    )
    decision = deterministic_decision(
        prediction_hash=context.predictions[0].row_hash,
        regime_hash=context.regimes[0].row_hash,
        capital_state_hash=context.capital_state.row_hash,
        risk_state_hash=context.risk_state.row_hash,
        cluster_state_hash="0" * 64,
    )
    writer = AppendOnlyRuntimeWriter(db)
    with pytest.raises(Exception, match="Missing cluster state"):
        writer.build_trade_signal_row(context, context.predictions[0], context.regimes[0], decision)


def test_writer_order_request_returns_none_for_zero_notional() -> None:
    db = _FakeDB()
    context = DeterministicContextBuilder(db).build_context(
        run_id=db.data["run_context"][0]["run_id"],
        account_id=1,
        run_mode="LIVE",
        hour_ts_utc=db.data["run_context"][0]["origin_hour_ts_utc"],
    )
    writer = AppendOnlyRuntimeWriter(db)
    decision = deterministic_decision(
        prediction_hash=context.predictions[0].row_hash,
        regime_hash=context.regimes[0].row_hash,
        capital_state_hash=context.capital_state.row_hash,
        risk_state_hash=context.risk_state.row_hash,
        cluster_state_hash=context.cluster_states[0].row_hash,
    )
    signal = writer.build_trade_signal_row(context, context.predictions[0], context.regimes[0], decision)
    signal = replace(signal, action="ENTER", target_position_notional=Decimal("0"))
    assert writer.build_order_request_row(context, signal) is None


def test_writer_builds_deterministic_fill_lot_and_trade_rows_with_correct_formulas() -> None:
    db = _FakeDB()
    context = DeterministicContextBuilder(db).build_context(
        run_id=db.data["run_context"][0]["run_id"],
        account_id=1,
        run_mode="LIVE",
        hour_ts_utc=db.data["run_context"][0]["origin_hour_ts_utc"],
    )
    writer = AppendOnlyRuntimeWriter(db)

    decision = deterministic_decision(
        prediction_hash=context.predictions[0].row_hash,
        regime_hash=context.regimes[0].row_hash,
        capital_state_hash=context.capital_state.row_hash,
        risk_state_hash=context.risk_state.row_hash,
        cluster_state_hash=context.cluster_states[0].row_hash,
    )
    signal = writer.build_trade_signal_row(context, context.predictions[0], context.regimes[0], decision)
    signal = replace(signal, action="ENTER", target_position_notional=Decimal("100.000000000000000000"))

    buy_order = writer.build_order_request_attempt_row(
        context=context,
        signal=signal,
        side="BUY",
        request_ts_utc=context.run_context.origin_hour_ts_utc,
        requested_qty=Decimal("1.000000000000000000"),
        requested_notional=Decimal("100.000000000000000000"),
        status="FILLED",
        attempt_seq=0,
    )
    fill_a = writer.build_order_fill_row(
        context=context,
        order=buy_order,
        fill_ts_utc=context.run_context.origin_hour_ts_utc,
        fill_price=Decimal("100.000000000000000000"),
        fill_qty=Decimal("1.000000000000000000"),
        liquidity_flag="TAKER",
        attempt_seq=0,
    )
    fill_b = writer.build_order_fill_row(
        context=context,
        order=buy_order,
        fill_ts_utc=context.run_context.origin_hour_ts_utc,
        fill_price=Decimal("100.000000000000000000"),
        fill_qty=Decimal("1.000000000000000000"),
        liquidity_flag="TAKER",
        attempt_seq=0,
    )
    assert fill_a.row_hash == fill_b.row_hash
    assert fill_a.fill_notional == Decimal("100.000000000000000000")
    assert fill_a.fee_paid == Decimal("0.400000000000000000")
    assert fill_a.slippage_cost == fill_a.fill_notional * fill_a.realized_slippage_rate

    lot = writer.build_position_lot_row(context=context, fill=fill_a)
    assert lot.open_notional == fill_a.fill_notional
    assert lot.remaining_qty == lot.open_qty

    sell_order = writer.build_order_request_attempt_row(
        context=context,
        signal=signal,
        side="SELL",
        request_ts_utc=context.run_context.origin_hour_ts_utc + timedelta(minutes=30),
        requested_qty=Decimal("0.500000000000000000"),
        requested_notional=Decimal("0.500000000000000000"),
        status="FILLED",
        attempt_seq=1,
    )
    exit_fill = writer.build_order_fill_row(
        context=context,
        order=sell_order,
        fill_ts_utc=context.run_context.origin_hour_ts_utc + timedelta(hours=2),
        fill_price=Decimal("110.000000000000000000"),
        fill_qty=Decimal("0.500000000000000000"),
        liquidity_flag="TAKER",
        attempt_seq=1,
    )
    trade = writer.build_executed_trade_row(
        context=context,
        lot_id=lot.lot_id,
        lot_asset_id=lot.asset_id,
        entry_ts_utc=lot.open_ts_utc,
        entry_price=lot.open_price,
        lot_open_qty=lot.open_qty,
        lot_open_fee=lot.open_fee,
        entry_fill_slippage_cost=fill_a.slippage_cost,
        parent_lot_hash=lot.row_hash,
        exit_fill=exit_fill,
        quantity=Decimal("0.500000000000000000"),
    )
    assert trade.gross_pnl == Decimal("5.000000000000000000")
    assert trade.net_pnl == trade.gross_pnl - trade.total_fee - trade.total_slippage_cost
    assert trade.holding_hours == 2


def test_writer_order_request_row_builds_for_enter_signal() -> None:
    db = _FakeDB()
    context = DeterministicContextBuilder(db).build_context(
        run_id=db.data["run_context"][0]["run_id"],
        account_id=1,
        run_mode="LIVE",
        hour_ts_utc=db.data["run_context"][0]["origin_hour_ts_utc"],
    )
    writer = AppendOnlyRuntimeWriter(db)
    decision = deterministic_decision(
        prediction_hash=context.predictions[0].row_hash,
        regime_hash=context.regimes[0].row_hash,
        capital_state_hash=context.capital_state.row_hash,
        risk_state_hash=context.risk_state.row_hash,
        cluster_state_hash=context.cluster_states[0].row_hash,
    )
    signal = writer.build_trade_signal_row(context, context.predictions[0], context.regimes[0], decision)
    signal = replace(signal, action="ENTER", target_position_notional=Decimal("10.000000000000000000"))
    row = writer.build_order_request_row(context, signal)
    assert row is not None
    assert row.side == "BUY"


def test_writer_validation_branches_raise_expected_errors() -> None:
    db = _FakeDB()
    context = DeterministicContextBuilder(db).build_context(
        run_id=db.data["run_context"][0]["run_id"],
        account_id=1,
        run_mode="LIVE",
        hour_ts_utc=db.data["run_context"][0]["origin_hour_ts_utc"],
    )
    writer = AppendOnlyRuntimeWriter(db)
    decision = deterministic_decision(
        prediction_hash=context.predictions[0].row_hash,
        regime_hash=context.regimes[0].row_hash,
        capital_state_hash=context.capital_state.row_hash,
        risk_state_hash=context.risk_state.row_hash,
        cluster_state_hash=context.cluster_states[0].row_hash,
    )
    signal = writer.build_trade_signal_row(context, context.predictions[0], context.regimes[0], decision)
    signal = replace(signal, action="ENTER", target_position_notional=Decimal("10.000000000000000000"))

    with pytest.raises(Exception, match="Invalid order side"):
        writer.build_order_request_attempt_row(
            context=context,
            signal=signal,
            side="HOLD",
            request_ts_utc=context.run_context.origin_hour_ts_utc,
            requested_qty=Decimal("1"),
            requested_notional=Decimal("1"),
            status="NEW",
            attempt_seq=0,
        )
    with pytest.raises(Exception, match="Invalid order status"):
        writer.build_order_request_attempt_row(
            context=context,
            signal=signal,
            side="BUY",
            request_ts_utc=context.run_context.origin_hour_ts_utc,
            requested_qty=Decimal("1"),
            requested_notional=Decimal("1"),
            status="UNKNOWN",
            attempt_seq=0,
        )
    with pytest.raises(Exception, match="requested_qty must be positive"):
        writer.build_order_request_attempt_row(
            context=context,
            signal=signal,
            side="BUY",
            request_ts_utc=context.run_context.origin_hour_ts_utc,
            requested_qty=Decimal("0"),
            requested_notional=Decimal("1"),
            status="NEW",
            attempt_seq=0,
        )
    with pytest.raises(Exception, match="requested_notional must be positive"):
        writer.build_order_request_attempt_row(
            context=context,
            signal=signal,
            side="BUY",
            request_ts_utc=context.run_context.origin_hour_ts_utc,
            requested_qty=Decimal("1"),
            requested_notional=Decimal("0"),
            status="NEW",
            attempt_seq=0,
        )
    with pytest.raises(Exception, match="attempt_seq must be non-negative"):
        writer.build_order_request_attempt_row(
            context=context,
            signal=signal,
            side="BUY",
            request_ts_utc=context.run_context.origin_hour_ts_utc,
            requested_qty=Decimal("1"),
            requested_notional=Decimal("1"),
            status="NEW",
            attempt_seq=-1,
        )

    order = writer.build_order_request_attempt_row(
        context=context,
        signal=signal,
        side="BUY",
        request_ts_utc=context.run_context.origin_hour_ts_utc,
        requested_qty=Decimal("1"),
        requested_notional=Decimal("1"),
        status="NEW",
        attempt_seq=0,
    )
    with pytest.raises(Exception, match="fill_qty must be positive"):
        writer.build_order_fill_row(
            context=context,
            order=order,
            fill_ts_utc=context.run_context.origin_hour_ts_utc,
            fill_price=Decimal("100"),
            fill_qty=Decimal("0"),
            liquidity_flag="TAKER",
            attempt_seq=0,
        )
    with pytest.raises(Exception, match="fill_price must be positive"):
        writer.build_order_fill_row(
            context=context,
            order=order,
            fill_ts_utc=context.run_context.origin_hour_ts_utc,
            fill_price=Decimal("0"),
            fill_qty=Decimal("1"),
            liquidity_flag="TAKER",
            attempt_seq=0,
        )
    with pytest.raises(Exception, match="Invalid liquidity_flag"):
        writer.build_order_fill_row(
            context=context,
            order=order,
            fill_ts_utc=context.run_context.origin_hour_ts_utc,
            fill_price=Decimal("100"),
            fill_qty=Decimal("1"),
            liquidity_flag="BAD",
            attempt_seq=0,
        )

    valid_fill = writer.build_order_fill_row(
        context=context,
        order=order,
        fill_ts_utc=context.run_context.origin_hour_ts_utc,
        fill_price=Decimal("100"),
        fill_qty=Decimal("1"),
        liquidity_flag="TAKER",
        attempt_seq=0,
    )
    bad_fill = replace(valid_fill, fill_qty=Decimal("0"))
    with pytest.raises(Exception, match="non-positive fill_qty"):
        writer.build_position_lot_row(context=context, fill=bad_fill)

    with pytest.raises(Exception, match="Executed trade quantity must be positive"):
        writer.build_executed_trade_row(
            context=context,
            lot_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            lot_asset_id=1,
            entry_ts_utc=context.run_context.origin_hour_ts_utc,
            entry_price=Decimal("100"),
            lot_open_qty=Decimal("1"),
            lot_open_fee=Decimal("1"),
            entry_fill_slippage_cost=Decimal("0.1"),
            parent_lot_hash="a" * 64,
            exit_fill=valid_fill,
            quantity=Decimal("0"),
        )
    with pytest.raises(Exception, match="Lot open quantity must be positive"):
        writer.build_executed_trade_row(
            context=context,
            lot_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
            lot_asset_id=1,
            entry_ts_utc=context.run_context.origin_hour_ts_utc,
            entry_price=Decimal("100"),
            lot_open_qty=Decimal("0"),
            lot_open_fee=Decimal("1"),
            entry_fill_slippage_cost=Decimal("0.1"),
            parent_lot_hash="b" * 64,
            exit_fill=valid_fill,
            quantity=Decimal("1"),
        )
