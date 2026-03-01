"""Unit tests for replay engine using deterministic in-memory DB."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID

import pytest

from execution.deterministic_context import DeterministicAbortError, DeterministicContextBuilder
from execution.replay_engine import (
    _cluster_state_hash_for_prediction,
    _compare_orders,
    _compare_risk_events,
    _compare_signals,
    _plan_runtime_artifacts,
    execute_hour,
    replay_hour,
)
from execution.runtime_writer import AppendOnlyRuntimeWriter


class _FakeDB:
    def __init__(self) -> None:
        hour = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.run_id = UUID("11111111-1111-4111-8111-111111111111")
        self.rows: dict[str, list[dict[str, Any]]] = {
            "run_context": [
                {
                    "run_id": self.run_id,
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
                    "run_id": self.run_id,
                    "account_id": 1,
                    "run_mode": "LIVE",
                    "asset_id": 1,
                    "hour_ts_utc": hour,
                    "horizon": "H1",
                    "model_version_id": 10,
                    "expected_return": Decimal("0.02"),
                    "upstream_hash": "d" * 64,
                    "row_hash": "0" * 64,
                    "training_window_id": None,
                    "lineage_backtest_run_id": None,
                    "lineage_fold_index": None,
                    "lineage_horizon": None,
                    "activation_id": 101,
                }
            ],
            "regime_output": [
                {
                    "run_id": self.run_id,
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
                    "activation_id": 101,
                }
            ],
            "risk_hourly_state": [
                {
                    "run_mode": "LIVE",
                    "account_id": 1,
                    "hour_ts_utc": hour,
                    "source_run_id": self.run_id,
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
                    "source_run_id": self.run_id,
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
                    "source_run_id": self.run_id,
                    "exposure_pct": Decimal("0.01"),
                    "max_cluster_exposure_pct": Decimal("0.08"),
                    "state_hash": "h" * 64,
                    "parent_risk_hash": "r" * 64,
                    "row_hash": "i" * 64,
                }
            ],
            "model_activation_gate": [
                {
                    "activation_id": 101,
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
            "trade_signal": [],
            "order_request": [],
            "risk_event": [],
            "cash_ledger": [],
            "model_training_window": [],
        }
        self._tx_open = False

    def begin(self) -> None:
        self._tx_open = True

    def commit(self) -> None:
        self._tx_open = False

    def rollback(self) -> None:
        self._tx_open = False

    def fetch_one(self, sql: str, params: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        rows = self.fetch_all(sql, params)
        return rows[0] if rows else None

    def fetch_all(self, sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        q = " ".join(sql.lower().split())
        if "select run_mode" in q and "from run_context" in q:
            return [{"run_mode": "LIVE"}] if self.rows["run_context"] else []
        if "with ordered as" in q and "from cash_ledger" in q:
            return [{"violations": 0}]
        if "from run_context" in q:
            return list(self.rows["run_context"])
        if "from model_prediction" in q:
            return list(self.rows["model_prediction"])
        if "from regime_output" in q:
            return list(self.rows["regime_output"])
        if "from risk_hourly_state" in q:
            return list(self.rows["risk_hourly_state"])
        if "from portfolio_hourly_state" in q:
            return list(self.rows["portfolio_hourly_state"])
        if "from cluster_exposure_hourly_state" in q:
            return list(self.rows["cluster_exposure_hourly_state"])
        if "from model_activation_gate" in q:
            return list(self.rows["model_activation_gate"])
        if "from asset_cluster_membership" in q:
            return list(self.rows["asset_cluster_membership"])
        if "from cost_profile" in q:
            return list(self.rows["cost_profile"])
        if "from trade_signal" in q:
            return list(self.rows["trade_signal"])
        if "from order_request" in q:
            return list(self.rows["order_request"])
        if "from risk_event" in q:
            return list(self.rows["risk_event"])
        if "from cash_ledger" in q:
            return list(self.rows["cash_ledger"])
        if "from model_training_window" in q:
            return []
        raise RuntimeError(f"Unhandled query: {sql}")

    def execute(self, sql: str, params: Mapping[str, Any]) -> None:
        q = " ".join(sql.lower().split())
        if "insert into trade_signal" in q:
            self.rows["trade_signal"].append(
                {
                    "signal_id": params["signal_id"],
                    "decision_hash": params["decision_hash"],
                    "row_hash": params["row_hash"],
                }
            )
            return
        if "insert into order_request" in q:
            self.rows["order_request"].append(
                {"order_id": params["order_id"], "row_hash": params["row_hash"]}
            )
            return
        if "insert into risk_event" in q:
            self.rows["risk_event"].append(
                {
                    "risk_event_id": params["risk_event_id"],
                    "row_hash": params["row_hash"],
                }
            )
            return
        raise RuntimeError(f"Unhandled execute SQL: {sql}")


def test_execute_and_replay_have_zero_mismatch() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    result = execute_hour(db, db.run_id, 1, "LIVE", hour)
    report = replay_hour(db, db.run_id, 1, hour)
    assert len(result.trade_signals) == 1
    assert len(result.order_requests) == 1
    assert report.mismatch_count == 0


def test_replay_reports_signal_hash_mismatch() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    execute_hour(db, db.run_id, 1, "LIVE", hour)

    # Tamper deterministic stored row to force replay mismatch.
    db.rows["trade_signal"][0]["row_hash"] = "0" * 64
    report = replay_hour(db, db.run_id, 1, hour)
    assert report.mismatch_count >= 1
    assert any(m.table_name == "trade_signal" and m.field_name == "row_hash" for m in report.mismatches)


def test_replay_without_run_context_aborts() -> None:
    db = _FakeDB()
    db.rows["run_context"] = []
    with pytest.raises(DeterministicAbortError, match="run_context not found for replay key"):
        replay_hour(
            db,
            UUID("11111111-1111-4111-8111-111111111111"),
            1,
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


class _FailingWriteDB(_FakeDB):
    def __init__(self) -> None:
        super().__init__()
        self.fail_on_table = "order_request"

    def execute(self, sql: str, params: Mapping[str, Any]) -> None:
        q = " ".join(sql.lower().split())
        if f"insert into {self.fail_on_table}" in q:
            raise RuntimeError("forced insert failure")
        super().execute(sql, params)


def test_execute_hour_rolls_back_when_write_fails() -> None:
    db = _FailingWriteDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    with pytest.raises(RuntimeError, match="forced insert failure"):
        execute_hour(db, db.run_id, 1, "LIVE", hour)
    assert db._tx_open is False


def test_plan_runtime_artifacts_missing_regime_aborts() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)
    context = replace(context, regimes=tuple())
    with pytest.raises(DeterministicAbortError, match="Missing regime"):
        _plan_runtime_artifacts(context, AppendOnlyRuntimeWriter(db))


def test_plan_runtime_artifacts_cost_gate_logs_risk_event() -> None:
    db = _FakeDB()
    db.rows["model_prediction"][0]["expected_return"] = Decimal("0.000100000000000000")
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)
    planned = _plan_runtime_artifacts(context, AppendOnlyRuntimeWriter(db))
    assert any(event.reason_code == "ENTER_COST_GATE_FAILED" for event in planned.risk_events)


def test_plan_runtime_artifacts_activation_gate_logs_risk_event() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    db.rows["model_activation_gate"][0]["validation_window_end_utc"] = hour + timedelta(hours=1)
    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)
    planned = _plan_runtime_artifacts(context, AppendOnlyRuntimeWriter(db))
    assert any(event.reason_code == "ACTIVATION_WINDOW_NOT_REACHED" for event in planned.risk_events)


def test_plan_runtime_artifacts_deduplicates_identical_risk_events() -> None:
    db = _FakeDB()
    db.rows["risk_hourly_state"][0]["halt_new_entries"] = True
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)

    # Simulate two deterministic predictions producing the same gate violation.
    context = replace(context, predictions=(context.predictions[0], context.predictions[0]))
    planned = _plan_runtime_artifacts(context, AppendOnlyRuntimeWriter(db))

    assert len(planned.trade_signals) == 2
    assert len(planned.order_requests) == 0
    assert len(planned.risk_events) == 1
    assert planned.risk_events[0].reason_code == "HALT_NEW_ENTRIES_ACTIVE"


def test_cluster_state_hash_helper_missing_membership_or_cluster_state_aborts() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)
    prediction = context.predictions[0]

    with pytest.raises(DeterministicAbortError, match="Missing cluster membership"):
        _cluster_state_hash_for_prediction(replace(context, memberships=tuple()), prediction)
    with pytest.raises(DeterministicAbortError, match="Missing cluster state"):
        _cluster_state_hash_for_prediction(replace(context, cluster_states=tuple()), prediction)


def test_compare_signals_presence_and_hash_mismatch_branches() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    result = execute_hour(db, db.run_id, 1, "LIVE", hour)
    signal = result.trade_signals[0]

    stored_extra = [
        {"signal_id": "extra", "decision_hash": "0" * 64, "row_hash": "0" * 64},
        {"signal_id": str(signal.signal_id), "decision_hash": signal.decision_hash, "row_hash": signal.row_hash},
    ]
    mismatches = _compare_signals(result.trade_signals, stored_extra)
    assert any(m.field_name == "presence" and m.actual == "stored_present" for m in mismatches)

    mismatches = _compare_signals(result.trade_signals, [])
    assert any(m.field_name == "presence" and m.actual == "stored_absent" for m in mismatches)

    stored_bad_decision = [
        {"signal_id": str(signal.signal_id), "decision_hash": "f" * 64, "row_hash": signal.row_hash}
    ]
    mismatches = _compare_signals(result.trade_signals, stored_bad_decision)
    assert any(m.field_name == "decision_hash" for m in mismatches)

    stored_bad_row = [
        {"signal_id": str(signal.signal_id), "decision_hash": signal.decision_hash, "row_hash": "f" * 64}
    ]
    mismatches = _compare_signals(result.trade_signals, stored_bad_row)
    assert any(m.field_name == "row_hash" for m in mismatches)


def test_compare_orders_presence_and_hash_mismatch_branches() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    result = execute_hour(db, db.run_id, 1, "LIVE", hour)
    order = result.order_requests[0]

    stored_extra = [
        {"order_id": "extra", "row_hash": "0" * 64},
        {"order_id": str(order.order_id), "row_hash": order.row_hash},
    ]
    mismatches = _compare_orders(result.order_requests, stored_extra)
    assert any(m.field_name == "presence" and m.actual == "stored_present" for m in mismatches)

    mismatches = _compare_orders(result.order_requests, [])
    assert any(m.field_name == "presence" and m.actual == "stored_absent" for m in mismatches)

    mismatches = _compare_orders(
        result.order_requests,
        [{"order_id": str(order.order_id), "row_hash": "f" * 64}],
    )
    assert any(m.field_name == "row_hash" for m in mismatches)


def test_compare_risk_events_presence_and_hash_mismatch_branches() -> None:
    db = _FakeDB()
    db.rows["model_prediction"][0]["expected_return"] = Decimal("0.000100000000000000")
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    result = execute_hour(db, db.run_id, 1, "LIVE", hour)
    risk_event = result.risk_events[0]

    stored_extra = [
        {"risk_event_id": "extra", "row_hash": "0" * 64},
        {"risk_event_id": str(risk_event.risk_event_id), "row_hash": risk_event.row_hash},
    ]
    mismatches = _compare_risk_events(result.risk_events, stored_extra)
    assert any(m.field_name == "presence" and m.actual == "stored_present" for m in mismatches)

    mismatches = _compare_risk_events(result.risk_events, [])
    assert any(m.field_name == "presence" and m.actual == "stored_absent" for m in mismatches)

    mismatches = _compare_risk_events(
        result.risk_events,
        [{"risk_event_id": str(risk_event.risk_event_id), "row_hash": "f" * 64}],
    )
    assert any(m.field_name == "row_hash" for m in mismatches)
