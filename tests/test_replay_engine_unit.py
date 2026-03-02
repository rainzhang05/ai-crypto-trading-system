"""Unit tests for replay engine using deterministic in-memory DB."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID

import pytest

import execution.replay_engine as replay_engine_module
from execution.decision_engine import DecisionResult, deterministic_decision
from execution.deterministic_context import DeterministicAbortError, DeterministicContextBuilder
from execution.deterministic_context import ExistingPositionLotState
from execution.replay_engine import (
    _OrderIntent,
    _allocate_sell_fill_fifo,
    _attempt_requested_notional,
    _build_fifo_lot_views_for_asset,
    _cluster_state_hash_for_prediction,
    _compare_fills,
    _compare_lots,
    _compare_orders,
    _compare_risk_events,
    _compare_signals,
    _compare_trades,
    _derive_order_intent,
    _plan_runtime_artifacts,
    _round_down_to_lot_size,
    execute_hour,
    replay_hour,
)
from execution.risk_runtime import RuntimeRiskProfile
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
                    "prob_up": Decimal("0.6500000000"),
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
            "position_hourly_state": [
                {
                    "run_mode": "LIVE",
                    "account_id": 1,
                    "asset_id": 1,
                    "hour_ts_utc": hour,
                    "source_run_id": self.run_id,
                    "quantity": Decimal("1.000000000000000000"),
                    "exposure_pct": Decimal("0.0100000000"),
                    "unrealized_pnl": Decimal("0"),
                    "row_hash": "p" * 64,
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
            "order_book_snapshot": [
                {
                    "asset_id": 1,
                    "snapshot_ts_utc": hour,
                    "hour_ts_utc": hour,
                    "best_bid_price": Decimal("99.000000000000000000"),
                    "best_ask_price": Decimal("100.000000000000000000"),
                    "best_bid_size": Decimal("1000000.000000000000000000"),
                    "best_ask_size": Decimal("1000000.000000000000000000"),
                    "row_hash": "y" * 64,
                }
            ],
            "market_ohlcv_hourly": [
                {
                    "asset_id": 1,
                    "hour_ts_utc": hour,
                    "close_price": Decimal("100.000000000000000000"),
                    "row_hash": "z" * 64,
                    "source_venue": "KRAKEN",
                }
            ],
            "trade_signal": [],
            "order_request": [],
            "order_fill": [],
            "position_lot": [],
            "executed_trade": [],
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

        def _filter_origin(rows: Sequence[Mapping[str, Any]]) -> Sequence[Mapping[str, Any]]:
            origin_hour = params.get("hour_ts_utc")
            run_id = str(params.get("run_id")) if params.get("run_id") is not None else None
            account_id = params.get("account_id")
            filtered: list[Mapping[str, Any]] = []
            for row in rows:
                row_origin = row.get("origin_hour_ts_utc")
                if "origin_hour_ts_utc < :hour_ts_utc" in q:
                    if row_origin is None or origin_hour is None or row_origin >= origin_hour:
                        continue
                if "origin_hour_ts_utc = :hour_ts_utc" in q:
                    if row_origin is None or origin_hour is None or row_origin != origin_hour:
                        continue
                if "run_id = :run_id" in q and run_id is not None and str(row.get("run_id")) != run_id:
                    continue
                if "account_id = :account_id" in q and account_id is not None and row.get("account_id") != account_id:
                    continue
                filtered.append(row)
            return filtered

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
        if "from account_risk_profile_assignment" in q:
            assignments = list(self.rows["account_risk_profile_assignment"])
            profiles = {row["profile_version"]: row for row in self.rows["risk_profile"]}
            joined: list[dict[str, Any]] = []
            for assignment in assignments:
                profile = profiles.get(assignment["profile_version"])
                if profile is None:
                    continue
                joined.append({**assignment, **profile})
            return joined
        if "from feature_snapshot" in q:
            return list(self.rows["feature_snapshot"])
        if "from position_hourly_state" in q:
            return list(self.rows["position_hourly_state"])
        if "from asset" in q:
            return list(self.rows["asset"])
        if "from order_book_snapshot" in q:
            return list(self.rows["order_book_snapshot"])
        if "from market_ohlcv_hourly" in q:
            return list(self.rows["market_ohlcv_hourly"])
        if "from trade_signal" in q:
            return list(self.rows["trade_signal"])
        if "from order_request" in q:
            return list(self.rows["order_request"])
        if "from order_fill" in q:
            return list(_filter_origin(self.rows["order_fill"]))
        if "from position_lot" in q:
            return list(_filter_origin(self.rows["position_lot"]))
        if "from executed_trade" in q:
            return list(_filter_origin(self.rows["executed_trade"]))
        if "from risk_event" in q:
            return list(_filter_origin(self.rows["risk_event"]))
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
        if "insert into order_fill" in q:
            self.rows["order_fill"].append(dict(params))
            return
        if "insert into position_lot" in q:
            self.rows["position_lot"].append(dict(params))
            return
        if "insert into executed_trade" in q:
            self.rows["executed_trade"].append(dict(params))
            return
        if "insert into risk_event" in q:
            self.rows["risk_event"].append(dict(params))
            return
        raise RuntimeError(f"Unhandled execute SQL: {sql}")


def test_execute_and_replay_have_zero_mismatch() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    result = execute_hour(db, db.run_id, 1, "LIVE", hour)
    report = replay_hour(db, db.run_id, 1, hour)
    assert len(result.trade_signals) == 1
    assert len(result.order_requests) == 1
    assert len(result.order_fills) == 1
    assert len(result.position_lots) == 1
    assert len(result.executed_trades) == 0
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
    assert (
        sum(
            1
            for event in planned.risk_events
            if event.reason_code == "HALT_NEW_ENTRIES_ACTIVE" and event.event_type != "DECISION_TRACE"
        )
        == 1
    )
    assert sum(1 for event in planned.risk_events if event.event_type == "DECISION_TRACE") == 2


def test_plan_runtime_artifacts_decision_trace_ids_unique_per_signal() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)

    base_prediction = context.predictions[0]
    alt_horizon_prediction = replace(base_prediction, horizon="H4")
    context = replace(context, predictions=(base_prediction, alt_horizon_prediction))

    planned = _plan_runtime_artifacts(context, AppendOnlyRuntimeWriter(db))
    decision_traces = tuple(event for event in planned.risk_events if event.event_type == "DECISION_TRACE")

    assert len(decision_traces) == 2
    assert len({event.risk_event_id for event in decision_traces}) == 2
    assert all(event.reason_code == "VOLATILITY_SIZED" for event in decision_traces)


def test_plan_runtime_artifacts_decision_trace_uses_volatility_fallback_reason() -> None:
    db = _FakeDB()
    db.rows["feature_snapshot"] = []
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)

    planned = _plan_runtime_artifacts(context, AppendOnlyRuntimeWriter(db))
    decision_trace = next(event for event in planned.risk_events if event.event_type == "DECISION_TRACE")

    assert decision_trace.reason_code == "VOLATILITY_FALLBACK_BASE"


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


def test_plan_runtime_artifacts_position_cap_logs_risk_event() -> None:
    db = _FakeDB()
    db.rows["portfolio_hourly_state"][0]["open_position_count"] = 10
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)
    planned = _plan_runtime_artifacts(context, AppendOnlyRuntimeWriter(db))
    assert any(event.reason_code == "MAX_CONCURRENT_POSITIONS_EXCEEDED" for event in planned.risk_events)


def test_plan_runtime_artifacts_severe_loss_entry_gate_logs_risk_event() -> None:
    db = _FakeDB()
    db.rows["risk_hourly_state"][0]["drawdown_pct"] = Decimal("0.1600000000")
    db.rows["risk_hourly_state"][0]["drawdown_tier"] = "DD15"
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)
    profile = RuntimeRiskProfile(severe_loss_drawdown_trigger=Decimal("0.1500000000"))
    planned = _plan_runtime_artifacts(
        context=context,
        writer=AppendOnlyRuntimeWriter(db),
        risk_profile=profile,
    )
    assert any(event.reason_code == "SEVERE_LOSS_RECOVERY_ENTRY_BLOCKED" for event in planned.risk_events)


def test_plan_runtime_artifacts_persistence_pending_forces_hold_for_exit_like_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDB()
    db.rows["model_prediction"][0]["expected_return"] = Decimal("-0.020000000000000000")
    db.rows["risk_profile"][0]["signal_persistence_required"] = 2
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)

    monkeypatch.setattr(
        replay_engine_module,
        "deterministic_decision",
        lambda **_: DecisionResult(
            decision_hash="d" * 64,
            action="EXIT",
            direction="FLAT",
            confidence=Decimal("0.5000000000"),
            position_size_fraction=Decimal("0.0000000000"),
        ),
    )

    planned = _plan_runtime_artifacts(context, AppendOnlyRuntimeWriter(db))
    assert len(planned.trade_signals) == 1
    assert planned.trade_signals[0].action == "HOLD"
    assert len(planned.order_requests) == 0
    decision_trace = next(event for event in planned.risk_events if event.event_type == "DECISION_TRACE")
    assert decision_trace.reason_code == "ADAPTIVE_HORIZON_PERSISTENCE_PENDING"


def test_plan_runtime_artifacts_dual_halt_and_kill_emits_kill_switch_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDB()
    db.rows["risk_hourly_state"][0]["halt_new_entries"] = True
    db.rows["risk_hourly_state"][0]["kill_switch_active"] = True
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)

    monkeypatch.setattr(
        replay_engine_module,
        "deterministic_decision",
        lambda **_: DecisionResult(
            decision_hash="e" * 64,
            action="ENTER",
            direction="LONG",
            confidence=Decimal("0.7000000000"),
            position_size_fraction=Decimal("0.0100000000"),
        ),
    )

    planned = _plan_runtime_artifacts(context, AppendOnlyRuntimeWriter(db))
    gating_events = tuple(event for event in planned.risk_events if event.event_type != "DECISION_TRACE")
    assert any(event.reason_code == "KILL_SWITCH_ACTIVE" for event in gating_events)
    assert all(event.reason_code != "HALT_NEW_ENTRIES_ACTIVE" for event in gating_events)


def test_plan_runtime_artifacts_exit_generates_sell_and_trade_with_preloaded_lot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    db.rows["model_prediction"][0]["expected_return"] = Decimal("-0.020000000000000000")

    open_fill_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    lot_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    db.rows["order_fill"].append(
        {
            "fill_id": str(open_fill_id),
            "order_id": str(UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")),
            "run_id": str(db.run_id),
            "run_mode": "LIVE",
            "account_id": 1,
            "asset_id": 1,
            "fill_ts_utc": hour - timedelta(hours=1),
            "fill_price": Decimal("95.000000000000000000"),
            "fill_qty": Decimal("1.000000000000000000"),
            "fill_notional": Decimal("95.000000000000000000"),
            "fee_paid": Decimal("0.380000000000000000"),
            "realized_slippage_rate": Decimal("0.000170"),
            "slippage_cost": Decimal("0.016150000000000000"),
            "row_hash": "a1" * 32,
            "origin_hour_ts_utc": hour - timedelta(hours=1),
        }
    )
    db.rows["position_lot"].append(
        {
            "lot_id": str(lot_id),
            "open_fill_id": str(open_fill_id),
            "run_id": str(db.run_id),
            "run_mode": "LIVE",
            "account_id": 1,
            "asset_id": 1,
            "open_ts_utc": hour - timedelta(hours=1),
            "open_price": Decimal("95.000000000000000000"),
            "open_qty": Decimal("1.000000000000000000"),
            "open_fee": Decimal("0.380000000000000000"),
            "remaining_qty": Decimal("1.000000000000000000"),
            "row_hash": "b1" * 32,
            "origin_hour_ts_utc": hour - timedelta(hours=1),
        }
    )

    monkeypatch.setattr(
        replay_engine_module,
        "deterministic_decision",
        lambda **_: DecisionResult(
            decision_hash="d" * 64,
            action="EXIT",
            direction="FLAT",
            confidence=Decimal("0.7000000000"),
            position_size_fraction=Decimal("0.0000000000"),
        ),
    )

    result = execute_hour(db, db.run_id, 1, "LIVE", hour)
    assert len(result.order_requests) == 1
    assert result.order_requests[0].side == "SELL"
    assert len(result.order_fills) == 1
    assert len(result.executed_trades) == 1
    assert result.executed_trades[0].lot_id == lot_id


def test_plan_runtime_artifacts_hold_derisk_emits_partial_sell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    db.rows["risk_hourly_state"][0]["drawdown_pct"] = Decimal("0.2500000000")
    db.rows["risk_hourly_state"][0]["drawdown_tier"] = "DD25"
    db.rows["model_prediction"][0]["prob_up"] = Decimal("0.5000000000")
    db.rows["model_prediction"][0]["expected_return"] = Decimal("0.001000000000000000")
    db.rows["position_hourly_state"][0]["quantity"] = Decimal("2.000000000000000000")
    db.rows["order_book_snapshot"][0]["best_bid_size"] = Decimal("1000000.000000000000000000")

    monkeypatch.setattr(
        replay_engine_module,
        "deterministic_decision",
        lambda **_: DecisionResult(
            decision_hash="e" * 64,
            action="HOLD",
            direction="FLAT",
            confidence=Decimal("0.6000000000"),
            position_size_fraction=Decimal("0.0000000000"),
        ),
    )

    result = execute_hour(db, db.run_id, 1, "LIVE", hour)
    assert len(result.order_requests) >= 1
    assert result.order_requests[0].side == "SELL"
    assert result.order_requests[0].requested_qty == Decimal("1.000000000000000000")
    assert any(event.reason_code == "SEVERE_RECOVERY_DERISK_ORDER_EMITTED" for event in result.risk_events)


def test_plan_runtime_artifacts_partial_fill_retries_and_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    db.rows["order_book_snapshot"][0]["best_ask_size"] = Decimal("1.000000000000000000")

    monkeypatch.setattr(
        replay_engine_module,
        "deterministic_decision",
        lambda **_: DecisionResult(
            decision_hash="f" * 64,
            action="ENTER",
            direction="LONG",
            confidence=Decimal("0.9000000000"),
            position_size_fraction=Decimal("0.9000000000"),
        ),
    )

    result = execute_hour(db, db.run_id, 1, "LIVE", hour)
    assert len(result.order_requests) == 4
    assert any(order.status == "PARTIAL" for order in result.order_requests)
    assert any(event.reason_code == "ORDER_RETRY_EXHAUSTED" for event in result.risk_events)


def test_compare_fills_presence_and_hash_mismatch_branches() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    result = execute_hour(db, db.run_id, 1, "LIVE", hour)
    fill = result.order_fills[0]

    stored_extra = [
        {"fill_id": "extra", "row_hash": "0" * 64},
        {"fill_id": str(fill.fill_id), "row_hash": fill.row_hash},
    ]
    mismatches = _compare_fills(result.order_fills, stored_extra)
    assert any(m.field_name == "presence" and m.actual == "stored_present" for m in mismatches)

    mismatches = _compare_fills(result.order_fills, [])
    assert any(m.field_name == "presence" and m.actual == "stored_absent" for m in mismatches)

    mismatches = _compare_fills(
        result.order_fills,
        [{"fill_id": str(fill.fill_id), "row_hash": "f" * 64}],
    )
    assert any(m.field_name == "row_hash" for m in mismatches)


def test_compare_lots_presence_and_hash_mismatch_branches() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    result = execute_hour(db, db.run_id, 1, "LIVE", hour)
    lot = result.position_lots[0]

    stored_extra = [
        {"lot_id": "extra", "row_hash": "0" * 64},
        {"lot_id": str(lot.lot_id), "row_hash": lot.row_hash},
    ]
    mismatches = _compare_lots(result.position_lots, stored_extra)
    assert any(m.field_name == "presence" and m.actual == "stored_present" for m in mismatches)

    mismatches = _compare_lots(result.position_lots, [])
    assert any(m.field_name == "presence" and m.actual == "stored_absent" for m in mismatches)

    mismatches = _compare_lots(
        result.position_lots,
        [{"lot_id": str(lot.lot_id), "row_hash": "f" * 64}],
    )
    assert any(m.field_name == "row_hash" for m in mismatches)


def test_compare_trades_presence_and_hash_mismatch_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    db.rows["model_prediction"][0]["expected_return"] = Decimal("-0.020000000000000000")

    open_fill_id = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    lot_id = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
    db.rows["order_fill"].append(
        {
            "fill_id": str(open_fill_id),
            "order_id": str(UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")),
            "run_id": str(db.run_id),
            "run_mode": "LIVE",
            "account_id": 1,
            "asset_id": 1,
            "fill_ts_utc": hour - timedelta(hours=1),
            "fill_price": Decimal("95.000000000000000000"),
            "fill_qty": Decimal("1.000000000000000000"),
            "fill_notional": Decimal("95.000000000000000000"),
            "fee_paid": Decimal("0.380000000000000000"),
            "realized_slippage_rate": Decimal("0.000170"),
            "slippage_cost": Decimal("0.016150000000000000"),
            "row_hash": "c1" * 32,
            "origin_hour_ts_utc": hour - timedelta(hours=1),
        }
    )
    db.rows["position_lot"].append(
        {
            "lot_id": str(lot_id),
            "open_fill_id": str(open_fill_id),
            "run_id": str(db.run_id),
            "run_mode": "LIVE",
            "account_id": 1,
            "asset_id": 1,
            "open_ts_utc": hour - timedelta(hours=1),
            "open_price": Decimal("95.000000000000000000"),
            "open_qty": Decimal("1.000000000000000000"),
            "open_fee": Decimal("0.380000000000000000"),
            "remaining_qty": Decimal("1.000000000000000000"),
            "row_hash": "d1" * 32,
            "origin_hour_ts_utc": hour - timedelta(hours=1),
        }
    )

    monkeypatch.setattr(
        replay_engine_module,
        "deterministic_decision",
        lambda **_: DecisionResult(
            decision_hash="1" * 64,
            action="EXIT",
            direction="FLAT",
            confidence=Decimal("0.7000000000"),
            position_size_fraction=Decimal("0.0000000000"),
        ),
    )
    result = execute_hour(db, db.run_id, 1, "LIVE", hour)
    trade = result.executed_trades[0]

    stored_extra = [
        {"trade_id": "extra", "row_hash": "0" * 64},
        {"trade_id": str(trade.trade_id), "row_hash": trade.row_hash},
    ]
    mismatches = _compare_trades(result.executed_trades, stored_extra)
    assert any(m.field_name == "presence" and m.actual == "stored_present" for m in mismatches)

    mismatches = _compare_trades(result.executed_trades, [])
    assert any(m.field_name == "presence" and m.actual == "stored_absent" for m in mismatches)

    mismatches = _compare_trades(
        result.executed_trades,
        [{"trade_id": str(trade.trade_id), "row_hash": "f" * 64}],
    )
    assert any(m.field_name == "row_hash" for m in mismatches)


def test_replay_exit_path_with_historical_lot_has_zero_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    db.rows["model_prediction"][0]["expected_return"] = Decimal("-0.020000000000000000")

    open_fill_id = UUID("12121212-1212-4121-8121-121212121212")
    lot_id = UUID("34343434-3434-4343-8343-343434343434")
    db.rows["order_fill"].append(
        {
            "fill_id": str(open_fill_id),
            "order_id": str(UUID("56565656-5656-4565-8565-565656565656")),
            "run_id": str(db.run_id),
            "run_mode": "LIVE",
            "account_id": 1,
            "asset_id": 1,
            "fill_ts_utc": hour - timedelta(hours=1),
            "fill_price": Decimal("95.000000000000000000"),
            "fill_qty": Decimal("1.000000000000000000"),
            "fill_notional": Decimal("95.000000000000000000"),
            "fee_paid": Decimal("0.380000000000000000"),
            "realized_slippage_rate": Decimal("0.000170"),
            "slippage_cost": Decimal("0.016150000000000000"),
            "row_hash": "e1" * 32,
            "origin_hour_ts_utc": hour - timedelta(hours=1),
        }
    )
    db.rows["position_lot"].append(
        {
            "lot_id": str(lot_id),
            "open_fill_id": str(open_fill_id),
            "run_id": str(db.run_id),
            "run_mode": "LIVE",
            "account_id": 1,
            "asset_id": 1,
            "open_ts_utc": hour - timedelta(hours=1),
            "open_price": Decimal("95.000000000000000000"),
            "open_qty": Decimal("1.000000000000000000"),
            "open_fee": Decimal("0.380000000000000000"),
            "remaining_qty": Decimal("1.000000000000000000"),
            "row_hash": "f1" * 32,
            "origin_hour_ts_utc": hour - timedelta(hours=1),
        }
    )

    monkeypatch.setattr(
        replay_engine_module,
        "deterministic_decision",
        lambda **_: DecisionResult(
            decision_hash="2" * 64,
            action="EXIT",
            direction="FLAT",
            confidence=Decimal("0.7000000000"),
            position_size_fraction=Decimal("0.0000000000"),
        ),
    )

    execute_hour(db, db.run_id, 1, "LIVE", hour)
    report = replay_hour(db, db.run_id, 1, hour)
    assert report.mismatch_count == 0


def test_derive_order_intent_validation_and_branch_coverage() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)
    writer = AppendOnlyRuntimeWriter(db)
    decision = deterministic_decision(
        prediction_hash=context.predictions[0].row_hash,
        regime_hash=context.regimes[0].row_hash,
        capital_state_hash=context.capital_state.row_hash,
        risk_state_hash=context.risk_state.row_hash,
        cluster_state_hash=context.cluster_states[0].row_hash,
    )
    signal = writer.build_trade_signal_row(context, context.predictions[0], context.regimes[0], decision)

    with pytest.raises(DeterministicAbortError, match="Missing asset precision"):
        _derive_order_intent(
            context=replace(context, asset_precisions=tuple()),
            writer=writer,
            signal=replace(signal, action="ENTER", target_position_notional=Decimal("1")),
            severe_recovery_reason_code="NO_SEVERE_LOSS_RECOVERY",
        )

    with pytest.raises(DeterministicAbortError, match="Invalid lot_size"):
        bad_asset = replace(context.asset_precisions[0], lot_size=Decimal("0"))
        _derive_order_intent(
            context=replace(context, asset_precisions=(bad_asset,)),
            writer=writer,
            signal=replace(signal, action="ENTER", target_position_notional=Decimal("1")),
            severe_recovery_reason_code="NO_SEVERE_LOSS_RECOVERY",
        )

    intent, _ = _derive_order_intent(
        context=context,
        writer=writer,
        signal=replace(signal, action="ENTER", target_position_notional=Decimal("1")),
        severe_recovery_reason_code="NO_SEVERE_LOSS_RECOVERY",
    )
    assert intent is not None

    no_inventory_context = replace(
        context,
        positions=(replace(context.positions[0], quantity=Decimal("0")),),
    )
    intent_none, events = _derive_order_intent(
        context=no_inventory_context,
        writer=writer,
        signal=replace(signal, action="EXIT"),
        severe_recovery_reason_code="NO_SEVERE_LOSS_RECOVERY",
    )
    assert intent_none is None
    assert any(event.reason_code == "NO_INVENTORY_FOR_SELL" for event in events)

    derisk_none, derisk_events = _derive_order_intent(
        context=no_inventory_context,
        writer=writer,
        signal=replace(signal, action="HOLD"),
        severe_recovery_reason_code="SEVERE_RECOVERY_DERISK_INTENT",
    )
    assert derisk_none is None
    assert any(event.reason_code == "NO_INVENTORY_FOR_SELL" for event in derisk_events)

    clipped_profile = replace(context.risk_profile, derisk_fraction=Decimal("1.5000000000"))
    _, clipped_events = _derive_order_intent(
        context=replace(context, risk_profile=clipped_profile),
        writer=writer,
        signal=replace(signal, action="HOLD"),
        severe_recovery_reason_code="SEVERE_RECOVERY_DERISK_INTENT",
    )
    assert any(event.reason_code == "SELL_QTY_CLIPPED_TO_INVENTORY" for event in clipped_events)

    huge_lot_context = replace(
        context,
        asset_precisions=(replace(context.asset_precisions[0], lot_size=Decimal("10.000000000000000000")),),
    )
    intent_none, events = _derive_order_intent(
        context=huge_lot_context,
        writer=writer,
        signal=replace(signal, action="HOLD"),
        severe_recovery_reason_code="SEVERE_RECOVERY_DERISK_INTENT",
    )
    assert intent_none is None
    assert any(event.reason_code == "ORDER_QTY_BELOW_LOT_SIZE" for event in events)


def test_materialize_order_lifecycle_unavailable_price_branches() -> None:
    db = _FakeDB()
    db.rows["order_book_snapshot"] = []
    db.rows["market_ohlcv_hourly"] = []
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)
    writer = AppendOnlyRuntimeWriter(db)

    decision = deterministic_decision(
        prediction_hash=context.predictions[0].row_hash,
        regime_hash=context.regimes[0].row_hash,
        capital_state_hash=context.capital_state.row_hash,
        risk_state_hash=context.risk_state.row_hash,
        cluster_state_hash=context.cluster_states[0].row_hash,
    )
    signal = writer.build_trade_signal_row(context, context.predictions[0], context.regimes[0], decision)
    signal = replace(signal, action="ENTER", target_position_notional=Decimal("2.000000000000000000"))
    intent = _OrderIntent(
        side="BUY",
        requested_qty=Decimal("2.000000000000000000"),
        requested_notional=Decimal("2.000000000000000000"),
        source_reason_code="SIGNAL_ENTER",
    )
    orders, fills, lots, trades, events = replay_engine_module._materialize_order_lifecycle(
        context=context,
        writer=writer,
        adapter=replay_engine_module.DeterministicExchangeSimulator(),
        signal=signal,
        intent=intent,
        planned_lots_by_asset={},
        planned_fills_by_id={},
        planned_lot_consumed_qty={},
    )
    assert len(orders) == 4
    assert all(order.status == "CANCELLED" for order in orders)
    assert len(fills) == 0
    assert len(lots) == 0
    assert len(trades) == 0
    assert any(event.reason_code == "ORDER_PRICE_UNAVAILABLE" for event in events)
    assert any(event.reason_code == "ORDER_RETRY_EXHAUSTED" for event in events)


def test_fifo_helpers_and_numeric_guards_cover_remaining_branches() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)
    writer = AppendOnlyRuntimeWriter(db)
    decision = deterministic_decision(
        prediction_hash=context.predictions[0].row_hash,
        regime_hash=context.regimes[0].row_hash,
        capital_state_hash=context.capital_state.row_hash,
        risk_state_hash=context.risk_state.row_hash,
        cluster_state_hash=context.cluster_states[0].row_hash,
    )
    signal = writer.build_trade_signal_row(context, context.predictions[0], context.regimes[0], decision)
    signal = replace(signal, action="ENTER", target_position_notional=Decimal("1.000000000000000000"))

    order = writer.build_order_request_attempt_row(
        context=context,
        signal=signal,
        side="BUY",
        request_ts_utc=hour,
        requested_qty=Decimal("1"),
        requested_notional=Decimal("1"),
        status="FILLED",
        attempt_seq=0,
    )
    fill = writer.build_order_fill_row(
        context=context,
        order=order,
        fill_ts_utc=hour,
        fill_price=Decimal("100"),
        fill_qty=Decimal("1"),
        liquidity_flag="TAKER",
        attempt_seq=0,
    )
    lot = writer.build_position_lot_row(context=context, fill=fill)

    # Missing open fill for existing lot branch.
    fabricated_lot = ExistingPositionLotState(
        lot_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        open_fill_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        run_id=context.run_context.run_id,
        run_mode=context.run_context.run_mode,
        account_id=context.run_context.account_id,
        asset_id=1,
        open_ts_utc=hour - timedelta(hours=1),
        open_price=Decimal("100"),
        open_qty=Decimal("1"),
        open_fee=Decimal("1"),
        remaining_qty=Decimal("1"),
        row_hash="a" * 64,
    )
    missing_existing_context = replace(
        context,
        existing_position_lots=(fabricated_lot,),
        existing_order_fills=tuple(),
    )
    with pytest.raises(DeterministicAbortError, match="Missing open_fill_id"):
        _build_fifo_lot_views_for_asset(
            context=missing_existing_context,
            asset_id=1,
            planned_lots_by_asset={},
            planned_fills_by_id={},
        )

    with pytest.raises(DeterministicAbortError, match="Missing planned fill"):
        _build_fifo_lot_views_for_asset(
            context=context,
            asset_id=1,
            planned_lots_by_asset={1: [lot]},
            planned_fills_by_id={},
        )

    # cover _allocate_sell_fill_fifo loop guards (break/continue)
    zero_fill = replace(fill, fill_qty=Decimal("0.000000000000000000"))
    residual = _allocate_sell_fill_fifo(
        context=context,
        writer=writer,
        fill=zero_fill,
        planned_lots_by_asset={1: [lot]},
        planned_fills_by_id={fill.fill_id: fill},
        planned_lot_consumed_qty={},
        trade_rows=[],
    )
    assert residual == Decimal("0.000000000000000000")

    residual = _allocate_sell_fill_fifo(
        context=context,
        writer=writer,
        fill=replace(fill, fill_qty=Decimal("1.000000000000000000")),
        planned_lots_by_asset={1: [lot]},
        planned_fills_by_id={fill.fill_id: fill},
        planned_lot_consumed_qty={lot.lot_id: lot.open_qty},
        trade_rows=[],
    )
    assert residual == Decimal("1.000000000000000000")

    # requested_notional helper guards
    with pytest.raises(DeterministicAbortError, match="requested_qty must be positive"):
        _attempt_requested_notional(
            intent=_OrderIntent(
                side="BUY",
                requested_qty=Decimal("1"),
                requested_notional=Decimal("1"),
                source_reason_code="SIGNAL_ENTER",
            ),
            requested_qty=Decimal("0"),
        )
    assert _attempt_requested_notional(
        intent=_OrderIntent(
            side="BUY",
            requested_qty=Decimal("1"),
            requested_notional=Decimal("0"),
            source_reason_code="SIGNAL_ENTER",
        ),
        requested_qty=Decimal("1"),
    ) == Decimal("1.000000000000000000")

    # lot-size helper guards
    assert _round_down_to_lot_size(Decimal("0"), Decimal("0.1")) == Decimal("0.000000000000000000")
    with pytest.raises(DeterministicAbortError, match="lot_size must be positive"):
        _round_down_to_lot_size(Decimal("1"), Decimal("0"))
    assert _round_down_to_lot_size(Decimal("0.01"), Decimal("1")) == Decimal("0.000000000000000000")
