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
