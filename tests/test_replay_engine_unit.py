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
from execution.deterministic_context import PriorEconomicState
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
        prior_hour = hour - timedelta(hours=1)
        self.run_id = UUID("11111111-1111-4111-8111-111111111111")
        self.prior_run_id = UUID("22222222-2222-4222-8222-222222222222")
        self.rows: dict[str, list[dict[str, Any]]] = {
            "run_context": [
                {
                    "run_id": self.run_id,
                    "account_id": 1,
                    "run_mode": "LIVE",
                    "hour_ts_utc": hour,
                    "origin_hour_ts_utc": hour,
                    "backtest_run_id": None,
                    "run_seed_hash": "a" * 64,
                    "context_hash": "b" * 64,
                    "replay_root_hash": "c" * 64,
                },
                {
                    "run_id": self.prior_run_id,
                    "account_id": 1,
                    "run_mode": "LIVE",
                    "hour_ts_utc": prior_hour,
                    "origin_hour_ts_utc": prior_hour,
                    "backtest_run_id": None,
                    "run_seed_hash": "a" * 64,
                    "context_hash": "b" * 64,
                    "replay_root_hash": "c" * 64,
                },
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
                    "hour_ts_utc": prior_hour,
                    "source_run_id": self.prior_run_id,
                    "portfolio_value": Decimal("10100"),
                    "peak_portfolio_value": Decimal("10100"),
                    "drawdown_pct": Decimal("0.0000000000"),
                    "drawdown_tier": "NORMAL",
                    "base_risk_fraction": Decimal("0.0200000000"),
                    "max_concurrent_positions": 10,
                    "max_total_exposure_pct": Decimal("0.2"),
                    "max_cluster_exposure_pct": Decimal("0.08"),
                    "halt_new_entries": False,
                    "kill_switch_active": False,
                    "kill_switch_reason": None,
                    "requires_manual_review": False,
                    "state_hash": "f" * 64,
                    "row_hash": "r" * 64,
                }
            ],
            "portfolio_hourly_state": [
                {
                    "run_mode": "LIVE",
                    "account_id": 1,
                    "hour_ts_utc": prior_hour,
                    "source_run_id": self.prior_run_id,
                    "cash_balance": Decimal("10000"),
                    "market_value": Decimal("100"),
                    "portfolio_value": Decimal("10100"),
                    "peak_portfolio_value": Decimal("10100"),
                    "drawdown_pct": Decimal("0.0000000000"),
                    "total_exposure_pct": Decimal("0.01"),
                    "open_position_count": 1,
                    "halted": False,
                    "reconciliation_hash": "g" * 64,
                    "row_hash": "g" * 64,
                }
            ],
            "cluster_exposure_hourly_state": [
                {
                    "run_mode": "LIVE",
                    "account_id": 1,
                    "cluster_id": 7,
                    "hour_ts_utc": prior_hour,
                    "source_run_id": self.prior_run_id,
                    "gross_exposure_notional": Decimal("100"),
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
            "backtest_run": [],
        }
        self._tx_open = False
        self._seed_current_hour_phase5_rows(hour)

    def _seed_current_hour_phase5_rows(self, hour: datetime) -> None:
        writer = AppendOnlyRuntimeWriter(self)
        builder = DeterministicContextBuilder(self)
        expected = replay_engine_module._build_expected_phase5_hourly_state(
            db=self,
            builder=builder,
            writer=writer,
            run_id=self.run_id,
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=hour,
        )
        self.rows["portfolio_hourly_state"].append(
            {
                "run_mode": expected.portfolio_row.run_mode,
                "account_id": expected.portfolio_row.account_id,
                "hour_ts_utc": expected.portfolio_row.hour_ts_utc,
                "source_run_id": expected.portfolio_row.source_run_id,
                "cash_balance": expected.portfolio_row.cash_balance,
                "market_value": expected.portfolio_row.market_value,
                "portfolio_value": expected.portfolio_row.portfolio_value,
                "peak_portfolio_value": expected.portfolio_row.peak_portfolio_value,
                "drawdown_pct": expected.portfolio_row.drawdown_pct,
                "total_exposure_pct": expected.portfolio_row.total_exposure_pct,
                "open_position_count": expected.portfolio_row.open_position_count,
                "halted": expected.portfolio_row.halted,
                "reconciliation_hash": expected.portfolio_row.reconciliation_hash,
                "row_hash": expected.portfolio_row.row_hash,
            }
        )
        self.rows["risk_hourly_state"].append(
            {
                "run_mode": expected.risk_row.run_mode,
                "account_id": expected.risk_row.account_id,
                "hour_ts_utc": expected.risk_row.hour_ts_utc,
                "source_run_id": expected.risk_row.source_run_id,
                "portfolio_value": expected.risk_row.portfolio_value,
                "peak_portfolio_value": expected.risk_row.peak_portfolio_value,
                "drawdown_pct": expected.risk_row.drawdown_pct,
                "drawdown_tier": expected.risk_row.drawdown_tier,
                "base_risk_fraction": expected.risk_row.base_risk_fraction,
                "max_concurrent_positions": expected.risk_row.max_concurrent_positions,
                "max_total_exposure_pct": expected.risk_row.max_total_exposure_pct,
                "max_cluster_exposure_pct": expected.risk_row.max_cluster_exposure_pct,
                "halt_new_entries": expected.risk_row.halt_new_entries,
                "kill_switch_active": expected.risk_row.kill_switch_active,
                "kill_switch_reason": expected.risk_row.kill_switch_reason,
                "requires_manual_review": expected.risk_row.requires_manual_review,
                "state_hash": expected.risk_row.state_hash,
                "row_hash": expected.risk_row.row_hash,
            }
        )
        self.rows["cluster_exposure_hourly_state"].extend(
            {
                "run_mode": row.run_mode,
                "account_id": row.account_id,
                "cluster_id": row.cluster_id,
                "hour_ts_utc": row.hour_ts_utc,
                "source_run_id": row.source_run_id,
                "gross_exposure_notional": row.gross_exposure_notional,
                "exposure_pct": row.exposure_pct,
                "max_cluster_exposure_pct": row.max_cluster_exposure_pct,
                "state_hash": row.state_hash,
                "parent_risk_hash": row.parent_risk_hash,
                "row_hash": row.row_hash,
            }
            for row in expected.cluster_rows
        )

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

        def _filter_common(
            rows: Sequence[Mapping[str, Any]],
            *,
            include_origin: bool = False,
        ) -> list[Mapping[str, Any]]:
            filtered: list[Mapping[str, Any]] = []
            run_id = params.get("run_id")
            source_run_id = params.get("source_run_id")
            account_id = params.get("account_id")
            run_mode = params.get("run_mode")
            asset_id = params.get("asset_id")
            hour_ts_utc = params.get("hour_ts_utc")
            for row in rows:
                if (
                    "source_run_id = :run_id" in q
                    and run_id is not None
                    and str(row.get("source_run_id")) != str(run_id)
                ):
                    continue
                if (
                    "run_id = :run_id" in q
                    and "source_run_id = :run_id" not in q
                    and run_id is not None
                    and str(row.get("run_id")) != str(run_id)
                ):
                    continue
                if (
                    "source_run_id = :source_run_id" in q
                    and source_run_id is not None
                    and str(row.get("source_run_id")) != str(source_run_id)
                ):
                    continue
                if "account_id = :account_id" in q and account_id is not None and row.get("account_id") != account_id:
                    continue
                if "run_mode = :run_mode" in q and run_mode is not None and str(row.get("run_mode")) != str(run_mode):
                    continue
                if "asset_id = :asset_id" in q and asset_id is not None and row.get("asset_id") != asset_id:
                    continue
                if "hour_ts_utc = :hour_ts_utc" in q and hour_ts_utc is not None and row.get("hour_ts_utc") != hour_ts_utc:
                    continue
                if "hour_ts_utc < :hour_ts_utc" in q and hour_ts_utc is not None and row.get("hour_ts_utc") is not None:
                    if row.get("hour_ts_utc") >= hour_ts_utc:
                        continue
                if "fill_ts_utc < :hour_ts_utc" in q and hour_ts_utc is not None and row.get("fill_ts_utc") is not None:
                    if row.get("fill_ts_utc") >= hour_ts_utc:
                        continue
                if include_origin:
                    row_origin = row.get("origin_hour_ts_utc")
                    if "origin_hour_ts_utc < :hour_ts_utc" in q:
                        if row_origin is None or hour_ts_utc is None or row_origin >= hour_ts_utc:
                            continue
                    if "origin_hour_ts_utc = :hour_ts_utc" in q:
                        if row_origin is None or hour_ts_utc is None or row_origin != hour_ts_utc:
                            continue
                    if (
                        "origin_hour_ts_utc = :origin_hour_ts_utc" in q
                        and params.get("origin_hour_ts_utc") is not None
                        and row_origin != params.get("origin_hour_ts_utc")
                    ):
                        continue
                filtered.append(row)
            return filtered

        if "select run_mode" in q and "from run_context" in q:
            rows = _filter_common(self.rows["run_context"])
            return [{"run_mode": str(rows[0]["run_mode"])}] if rows else []
        if "with ordered as" in q and "from cash_ledger" in q:
            return [{"violations": 0}]
        if "from run_context" in q:
            rows = _filter_common(self.rows["run_context"])
            if "order by origin_hour_ts_utc asc, run_id asc" in q:
                rows.sort(key=lambda item: (item["origin_hour_ts_utc"], str(item["run_id"])))
            return rows
        if "from model_prediction" in q:
            return _filter_common(self.rows["model_prediction"])
        if "from regime_output" in q:
            return _filter_common(self.rows["regime_output"])
        if "from risk_hourly_state" in q:
            rows = _filter_common(self.rows["risk_hourly_state"])
            if "order by hour_ts_utc desc" in q:
                rows.sort(key=lambda item: item["hour_ts_utc"], reverse=True)
            return rows
        if "from portfolio_hourly_state" in q:
            rows = _filter_common(self.rows["portfolio_hourly_state"])
            if "order by hour_ts_utc desc" in q:
                rows.sort(key=lambda item: item["hour_ts_utc"], reverse=True)
            return rows
        if "from cluster_exposure_hourly_state" in q:
            rows = _filter_common(self.rows["cluster_exposure_hourly_state"])
            if "order by cluster_id asc, hour_ts_utc desc" in q:
                rows.sort(key=lambda item: item["hour_ts_utc"], reverse=True)
                rows.sort(key=lambda item: item["cluster_id"])
            elif "order by cluster_id asc" in q:
                rows.sort(key=lambda item: item["cluster_id"])
            return rows
        if "from model_activation_gate" in q:
            return list(self.rows["model_activation_gate"])
        if "from asset_cluster_membership" in q:
            rows = list(self.rows["asset_cluster_membership"])
            if "order by asset_id asc, effective_from_utc desc" in q:
                rows.sort(key=lambda item: (item["asset_id"], -int(item["effective_from_utc"].timestamp())))
            return rows
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
            return _filter_common(self.rows["position_hourly_state"])
        if "from asset" in q:
            return list(self.rows["asset"])
        if "from order_book_snapshot" in q:
            rows = list(self.rows["order_book_snapshot"])
            if "where asset_id = :asset_id" in q and params.get("asset_id") is not None:
                rows = [row for row in rows if row.get("asset_id") == params.get("asset_id")]
            if "snapshot_ts_utc <= :hour_ts_utc" in q and params.get("hour_ts_utc") is not None:
                rows = [row for row in rows if row.get("snapshot_ts_utc") <= params.get("hour_ts_utc")]
            if "order by snapshot_ts_utc desc" in q:
                rows.sort(key=lambda item: item["snapshot_ts_utc"], reverse=True)
            return rows
        if "from market_ohlcv_hourly" in q:
            rows = list(self.rows["market_ohlcv_hourly"])
            if "where asset_id = :asset_id" in q and params.get("asset_id") is not None:
                rows = [row for row in rows if row.get("asset_id") == params.get("asset_id")]
            if "hour_ts_utc <= :hour_ts_utc" in q and params.get("hour_ts_utc") is not None:
                rows = [row for row in rows if row.get("hour_ts_utc") <= params.get("hour_ts_utc")]
            if "order by hour_ts_utc desc" in q:
                rows.sort(key=lambda item: item["hour_ts_utc"], reverse=True)
            return rows
        if "from trade_signal" in q:
            return _filter_common(self.rows["trade_signal"])
        if "from order_request" in q:
            return _filter_common(self.rows["order_request"], include_origin=True)
        if "from order_fill" in q:
            rows = _filter_common(self.rows["order_fill"], include_origin=True)
            return list(_filter_origin(rows))
        if "from position_lot" in q:
            rows = _filter_common(self.rows["position_lot"], include_origin=True)
            return list(_filter_origin(rows))
        if "from executed_trade" in q:
            rows = _filter_common(self.rows["executed_trade"], include_origin=True)
            return list(_filter_origin(rows))
        if "from risk_event" in q:
            rows = _filter_common(self.rows["risk_event"], include_origin=True)
            return list(_filter_origin(rows))
        if "from cash_ledger" in q:
            rows = _filter_common(self.rows["cash_ledger"], include_origin=True)
            if "event_ts_utc < :hour_ts_utc" in q and params.get("hour_ts_utc") is not None:
                rows = [row for row in rows if row.get("event_ts_utc") < params.get("hour_ts_utc")]
            if "order by ledger_seq desc" in q:
                rows.sort(key=lambda item: item["ledger_seq"], reverse=True)
            elif "order by ledger_seq asc" in q:
                rows.sort(key=lambda item: item["ledger_seq"])
            return rows
        if "from backtest_run" in q:
            return list(self.rows.get("backtest_run", []))
        if "from model_training_window" in q:
            return []
        raise RuntimeError(f"Unhandled query: {sql}")

    def execute(self, sql: str, params: Mapping[str, Any]) -> None:
        q = " ".join(sql.lower().split())
        if "insert into trade_signal" in q:
            self.rows["trade_signal"].append(dict(params))
            return
        if "insert into order_request" in q:
            self.rows["order_request"].append(dict(params))
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
        if "insert into portfolio_hourly_state" in q:
            self.rows["portfolio_hourly_state"].append(dict(params))
            return
        if "insert into risk_hourly_state" in q:
            self.rows["risk_hourly_state"].append(dict(params))
            return
        if "insert into cluster_exposure_hourly_state" in q:
            self.rows["cluster_exposure_hourly_state"].append(dict(params))
            return
        if "insert into cash_ledger" in q:
            self.rows["cash_ledger"].append(dict(params))
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
    assert len(result.cash_ledger_rows) == 1
    assert len(result.portfolio_hourly_states) == 1
    assert len(result.cluster_exposure_hourly_states) == 1
    assert len(result.risk_hourly_states) == 1
    assert report.mismatch_count == 0


def test_execute_hour_phase5_state_insert_path_when_current_rows_missing() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    db.rows["portfolio_hourly_state"] = [
        row for row in db.rows["portfolio_hourly_state"] if row["hour_ts_utc"] < hour
    ]
    db.rows["risk_hourly_state"] = [
        row for row in db.rows["risk_hourly_state"] if row["hour_ts_utc"] < hour
    ]
    db.rows["cluster_exposure_hourly_state"] = [
        row for row in db.rows["cluster_exposure_hourly_state"] if row["hour_ts_utc"] < hour
    ]

    result = execute_hour(db, db.run_id, 1, "LIVE", hour)
    assert len(result.portfolio_hourly_states) == 1
    assert len(result.risk_hourly_states) == 1
    assert len(result.cluster_exposure_hourly_states) == 1
    assert any(
        row["hour_ts_utc"] == hour and str(row["source_run_id"]) == str(db.run_id)
        for row in db.rows["portfolio_hourly_state"]
    )


def test_execute_hour_phase5_state_idempotent_when_hash_matches() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    before_portfolio = len(
        [
            row
            for row in db.rows["portfolio_hourly_state"]
            if row["hour_ts_utc"] == hour and str(row["source_run_id"]) == str(db.run_id)
        ]
    )
    before_risk = len(
        [
            row
            for row in db.rows["risk_hourly_state"]
            if row["hour_ts_utc"] == hour and str(row["source_run_id"]) == str(db.run_id)
        ]
    )
    before_cluster = len(
        [
            row
            for row in db.rows["cluster_exposure_hourly_state"]
            if row["hour_ts_utc"] == hour and str(row["source_run_id"]) == str(db.run_id)
        ]
    )

    execute_hour(db, db.run_id, 1, "LIVE", hour)

    after_portfolio = len(
        [
            row
            for row in db.rows["portfolio_hourly_state"]
            if row["hour_ts_utc"] == hour and str(row["source_run_id"]) == str(db.run_id)
        ]
    )
    after_risk = len(
        [
            row
            for row in db.rows["risk_hourly_state"]
            if row["hour_ts_utc"] == hour and str(row["source_run_id"]) == str(db.run_id)
        ]
    )
    after_cluster = len(
        [
            row
            for row in db.rows["cluster_exposure_hourly_state"]
            if row["hour_ts_utc"] == hour and str(row["source_run_id"]) == str(db.run_id)
        ]
    )
    assert after_portfolio == before_portfolio
    assert after_risk == before_risk
    assert after_cluster == before_cluster


def test_execute_hour_phase5_state_hash_mismatch_aborts() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    for row in db.rows["portfolio_hourly_state"]:
        if row["hour_ts_utc"] == hour and str(row["source_run_id"]) == str(db.run_id):
            row["row_hash"] = "0" * 64
            break

    with pytest.raises(DeterministicAbortError, match="portfolio_hourly_state hash mismatch"):
        execute_hour(db, db.run_id, 1, "LIVE", hour)


def test_phase5_bootstrap_cash_branches_for_backtest_and_paper_modes() -> None:
    backtest_db = _FakeDB()
    hour = backtest_db.rows["run_context"][0]["origin_hour_ts_utc"]
    backtest_db.rows["run_context"][0]["run_mode"] = "BACKTEST"
    backtest_db.rows["run_context"][0]["backtest_run_id"] = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    backtest_db.rows["model_prediction"][0]["run_mode"] = "BACKTEST"
    backtest_db.rows["position_hourly_state"][0]["run_mode"] = "BACKTEST"
    backtest_db.rows["portfolio_hourly_state"] = []
    backtest_db.rows["risk_hourly_state"] = []
    backtest_db.rows["cluster_exposure_hourly_state"] = []
    backtest_db.rows["cash_ledger"] = []
    backtest_db.rows["backtest_run"] = [
        {
            "backtest_run_id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            "initial_capital": Decimal("5000.000000000000000000"),
        }
    ]
    backtest_state = replay_engine_module._build_expected_phase5_hourly_state(
        db=backtest_db,
        builder=DeterministicContextBuilder(backtest_db),
        writer=AppendOnlyRuntimeWriter(backtest_db),
        run_id=backtest_db.run_id,
        account_id=1,
        run_mode="BACKTEST",
        hour_ts_utc=hour,
    )
    assert backtest_state.portfolio_row.cash_balance == Decimal("5000.000000000000000000")

    paper_db = _FakeDB()
    paper_db.rows["run_context"][0]["run_mode"] = "PAPER"
    paper_db.rows["model_prediction"][0]["run_mode"] = "PAPER"
    paper_db.rows["regime_output"][0]["run_mode"] = "PAPER"
    paper_db.rows["position_hourly_state"][0]["run_mode"] = "PAPER"
    paper_db.rows["portfolio_hourly_state"] = []
    paper_db.rows["risk_hourly_state"] = []
    paper_db.rows["cluster_exposure_hourly_state"] = []
    paper_db.rows["cash_ledger"] = []
    with pytest.raises(DeterministicAbortError, match="requires prior portfolio/ledger bootstrap"):
        replay_engine_module._build_expected_phase5_hourly_state(
            db=paper_db,
            builder=DeterministicContextBuilder(paper_db),
            writer=AppendOnlyRuntimeWriter(paper_db),
            run_id=paper_db.run_id,
            account_id=1,
            run_mode="PAPER",
            hour_ts_utc=hour,
        )


def test_replay_reports_phase5_mismatches() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    execute_hour(db, db.run_id, 1, "LIVE", hour)

    mutated_risk_hash = "1" * 64
    for row in db.rows["portfolio_hourly_state"]:
        if row["hour_ts_utc"] == hour and str(row["source_run_id"]) == str(db.run_id):
            row["row_hash"] = "0" * 64
    for row in db.rows["risk_hourly_state"]:
        if row["hour_ts_utc"] == hour and str(row["source_run_id"]) == str(db.run_id):
            row["row_hash"] = mutated_risk_hash
    for row in db.rows["cluster_exposure_hourly_state"]:
        if row["hour_ts_utc"] == hour and str(row["source_run_id"]) == str(db.run_id):
            row["parent_risk_hash"] = mutated_risk_hash
            row["row_hash"] = "2" * 64
    if db.rows["cash_ledger"]:
        db.rows["cash_ledger"][0]["row_hash"] = "3" * 64

    report = replay_hour(db, db.run_id, 1, hour)
    mismatched_tables = {m.table_name for m in report.mismatches}
    assert "cash_ledger" in mismatched_tables
    assert "portfolio_hourly_state" in mismatched_tables
    assert "cluster_exposure_hourly_state" in mismatched_tables
    assert "risk_hourly_state" in mismatched_tables


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
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    for row in db.rows["risk_hourly_state"]:
        if row["hour_ts_utc"] == hour and str(row["source_run_id"]) == str(db.run_id):
            row["halt_new_entries"] = True
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
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    for row in db.rows["portfolio_hourly_state"]:
        if row["hour_ts_utc"] == hour and str(row["source_run_id"]) == str(db.run_id):
            row["open_position_count"] = 10
    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)
    planned = _plan_runtime_artifacts(context, AppendOnlyRuntimeWriter(db))
    assert any(event.reason_code == "MAX_CONCURRENT_POSITIONS_EXCEEDED" for event in planned.risk_events)


def test_plan_runtime_artifacts_severe_loss_entry_gate_logs_risk_event() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    for row in db.rows["risk_hourly_state"]:
        if row["hour_ts_utc"] == hour and str(row["source_run_id"]) == str(db.run_id):
            row["drawdown_pct"] = Decimal("0.1600000000")
            row["drawdown_tier"] = "DD15"
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
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    for row in db.rows["risk_hourly_state"]:
        if row["hour_ts_utc"] == hour and str(row["source_run_id"]) == str(db.run_id):
            row["halt_new_entries"] = True
            row["kill_switch_active"] = True
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

    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)
    context = replace(
        context,
        risk_state=replace(
            context.risk_state,
            drawdown_pct=Decimal("0.2500000000"),
            drawdown_tier="HALT20",
            halt_new_entries=False,
        ),
    )
    planned = _plan_runtime_artifacts(context, AppendOnlyRuntimeWriter(db))
    assert len(planned.order_requests) >= 1
    assert planned.order_requests[0].side == "SELL"
    assert planned.order_requests[0].requested_qty == Decimal("1.000000000000000000")
    assert any(event.reason_code == "SEVERE_RECOVERY_DERISK_ORDER_EMITTED" for event in planned.risk_events)


def test_plan_runtime_artifacts_partial_fill_retries_and_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    db.rows["order_book_snapshot"][0]["best_ask_size"] = Decimal("0.500000000000000000")

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


def test_phase5_internal_parsers_and_membership_guards() -> None:
    assert replay_engine_module._to_decimal("1.25") == Decimal("1.25")
    dt_obj = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert replay_engine_module._to_datetime(dt_obj) == dt_obj
    parsed_dt = replay_engine_module._to_datetime("2026-01-01T00:00:00+00:00")
    assert parsed_dt == datetime(2026, 1, 1, tzinfo=timezone.utc)

    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    assert replay_engine_module._load_active_memberships(db, [], hour) == {}

    db.rows["asset_cluster_membership"].append(
        {
            "membership_id": 701,
            "asset_id": 1,
            "cluster_id": 8,
            "membership_hash": "n" * 64,
            "effective_from_utc": hour - timedelta(days=2),
        }
    )
    db.rows["asset_cluster_membership"].append(
        {
            "membership_id": 702,
            "asset_id": 2,
            "cluster_id": 9,
            "membership_hash": "o" * 64,
            "effective_from_utc": hour - timedelta(days=1),
        }
    )
    memberships = replay_engine_module._load_active_memberships(db, [1], hour)
    assert memberships == {1: 7}

    with pytest.raises(DeterministicAbortError, match="Missing cluster membership"):
        replay_engine_module._load_active_memberships(db, [999], hour)


def test_phase5_mark_price_fallbacks_and_missing_price_abort() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]

    db.rows["order_book_snapshot"] = []
    db.rows["market_ohlcv_hourly"] = [
        {
            "asset_id": 1,
            "hour_ts_utc": hour,
            "close_price": Decimal("88.000000000000000000"),
            "row_hash": "p" * 64,
            "source_venue": "KRAKEN",
        }
    ]
    assert (
        replay_engine_module._resolve_mark_price(
            db=db,
            account_id=1,
            run_mode="LIVE",
            asset_id=1,
            hour_ts_utc=hour,
        )
        == Decimal("88.000000000000000000")
    )

    db.rows["market_ohlcv_hourly"] = []
    db.rows["order_fill"] = [
        {
            "fill_id": str(UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")),
            "order_id": str(UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")),
            "run_id": str(db.run_id),
            "run_mode": "LIVE",
            "account_id": 1,
            "asset_id": 1,
            "fill_ts_utc": hour - timedelta(hours=1),
            "fill_price": Decimal("77.000000000000000000"),
            "fill_qty": Decimal("1.000000000000000000"),
            "fill_notional": Decimal("77.000000000000000000"),
            "fee_paid": Decimal("0"),
            "realized_slippage_rate": Decimal("0"),
            "slippage_cost": Decimal("0"),
            "row_hash": "q" * 64,
            "origin_hour_ts_utc": hour - timedelta(hours=1),
        }
    ]
    assert (
        replay_engine_module._resolve_mark_price(
            db=db,
            account_id=1,
            run_mode="LIVE",
            asset_id=1,
            hour_ts_utc=hour,
        )
        == Decimal("77.000000000000000000")
    )

    db.rows["order_fill"] = []
    builder = DeterministicContextBuilder(db)
    writer = AppendOnlyRuntimeWriter(db)
    with pytest.raises(DeterministicAbortError, match="Unable to determine mark price"):
        replay_engine_module._build_expected_phase5_hourly_state(
            db=db,
            builder=builder,
            writer=writer,
            run_id=db.run_id,
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=hour,
        )


def test_phase5_expected_state_guards_and_position_skip() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    builder = DeterministicContextBuilder(db)
    writer = AppendOnlyRuntimeWriter(db)

    db.rows["model_prediction"] = []
    with pytest.raises(DeterministicAbortError, match="No model_prediction rows available"):
        replay_engine_module._build_expected_phase5_hourly_state(
            db=db,
            builder=builder,
            writer=writer,
            run_id=db.run_id,
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=hour,
        )

    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    db.rows["position_hourly_state"][0]["quantity"] = Decimal("0")
    result = replay_engine_module._build_expected_phase5_hourly_state(
        db=db,
        builder=DeterministicContextBuilder(db),
        writer=AppendOnlyRuntimeWriter(db),
        run_id=db.run_id,
        account_id=1,
        run_mode="LIVE",
        hour_ts_utc=hour,
    )
    assert result.portfolio_row.market_value == Decimal("0.000000000000000000")
    assert result.portfolio_row.open_position_count == 0


def test_phase5_ensure_hourly_state_conflict_paths() -> None:
    hour = _FakeDB().rows["run_context"][0]["origin_hour_ts_utc"]

    db = _FakeDB()
    for row in db.rows["risk_hourly_state"]:
        if row["hour_ts_utc"] == hour and str(row["source_run_id"]) == str(db.run_id):
            row["row_hash"] = "0" * 64
    with pytest.raises(DeterministicAbortError, match="risk_hourly_state hash mismatch"):
        replay_engine_module._ensure_phase5_hourly_state(
            db=db,
            builder=DeterministicContextBuilder(db),
            writer=AppendOnlyRuntimeWriter(db),
            run_id=db.run_id,
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=hour,
        )

    db = _FakeDB()
    db.rows["cluster_exposure_hourly_state"].append(
        {
            "run_mode": "LIVE",
            "account_id": 1,
            "cluster_id": 999,
            "hour_ts_utc": hour,
            "source_run_id": db.run_id,
            "gross_exposure_notional": Decimal("0"),
            "exposure_pct": Decimal("0"),
            "max_cluster_exposure_pct": Decimal("0.0800000000"),
            "state_hash": "1" * 64,
            "parent_risk_hash": "2" * 64,
            "row_hash": "3" * 64,
        }
    )
    with pytest.raises(DeterministicAbortError, match="contains unexpected cluster_id"):
        replay_engine_module._ensure_phase5_hourly_state(
            db=db,
            builder=DeterministicContextBuilder(db),
            writer=AppendOnlyRuntimeWriter(db),
            run_id=db.run_id,
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=hour,
        )

    db = _FakeDB()
    for row in db.rows["cluster_exposure_hourly_state"]:
        if row["hour_ts_utc"] == hour and str(row["source_run_id"]) == str(db.run_id):
            row["row_hash"] = "4" * 64
    with pytest.raises(DeterministicAbortError, match="hash mismatch for cluster_id"):
        replay_engine_module._ensure_phase5_hourly_state(
            db=db,
            builder=DeterministicContextBuilder(db),
            writer=AppendOnlyRuntimeWriter(db),
            run_id=db.run_id,
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=hour,
        )


def test_phase5_cash_ledger_builder_and_ensure_conflicts() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)
    writer = AppendOnlyRuntimeWriter(db)
    planned = _plan_runtime_artifacts(context, writer)

    prior = PriorEconomicState(
        ledger_seq=12,
        balance_before=Decimal("5000.000000000000000000"),
        balance_after=Decimal("5100.000000000000000000"),
        prev_ledger_hash="a" * 64,
        ledger_hash="b" * 64,
        row_hash="c" * 64,
        event_ts_utc=hour - timedelta(hours=1),
    )
    expected_rows = replay_engine_module._build_expected_cash_ledger_rows(
        writer=writer,
        context=context,
        order_requests=planned.order_requests,
        order_fills=planned.order_fills,
        prior_ledger_state=prior,
    )
    assert expected_rows[0].balance_before == Decimal("5100.000000000000000000")

    with pytest.raises(DeterministicAbortError, match="Missing order_request side"):
        replay_engine_module._build_expected_cash_ledger_rows(
            writer=writer,
            context=context,
            order_requests=tuple(),
            order_fills=planned.order_fills,
            prior_ledger_state=None,
        )

    db.rows["cash_ledger"] = [
        {
            "run_id": str(db.run_id),
            "account_id": 1,
            "origin_hour_ts_utc": hour,
            "ledger_seq": 999,
            "row_hash": "0" * 64,
        }
    ]
    with pytest.raises(DeterministicAbortError, match="unexpected ledger_seq"):
        replay_engine_module._ensure_phase5_cash_ledger_rows(
            db=db,
            writer=AppendOnlyRuntimeWriter(db),
            context=context,
            order_requests=planned.order_requests,
            order_fills=planned.order_fills,
            prior_ledger_state=context.prior_economic_state,
        )

    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)
    writer = AppendOnlyRuntimeWriter(db)
    planned = _plan_runtime_artifacts(context, writer)
    expected_rows = replay_engine_module._build_expected_cash_ledger_rows(
        writer=writer,
        context=context,
        order_requests=planned.order_requests,
        order_fills=planned.order_fills,
        prior_ledger_state=None,
    )
    db.rows["cash_ledger"] = [
        {
            "run_id": str(db.run_id),
            "account_id": 1,
            "origin_hour_ts_utc": hour,
            "ledger_seq": expected_rows[0].ledger_seq,
            "row_hash": "9" * 64,
        }
    ]
    with pytest.raises(DeterministicAbortError, match="cash_ledger hash mismatch"):
        replay_engine_module._ensure_phase5_cash_ledger_rows(
            db=db,
            writer=AppendOnlyRuntimeWriter(db),
            context=context,
            order_requests=planned.order_requests,
            order_fills=planned.order_fills,
            prior_ledger_state=context.prior_economic_state,
        )


def test_phase5_cash_bootstrap_and_reference_price_helpers() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    context = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)
    builder = DeterministicContextBuilder(db)

    assert (
        replay_engine_module._resolve_starting_cash_balance(
            builder=builder,
            run_context=context.run_context,
            run_mode="LIVE",
            prior_ledger=PriorEconomicState(
                ledger_seq=1,
                balance_before=Decimal("10"),
                balance_after=Decimal("20"),
                prev_ledger_hash=None,
                ledger_hash="a" * 64,
                row_hash="b" * 64,
                event_ts_utc=hour - timedelta(hours=1),
            ),
            prior_portfolio=None,
        )
        == Decimal("20.000000000000000000")
    )

    with pytest.raises(DeterministicAbortError, match="missing backtest_run_id"):
        replay_engine_module._resolve_starting_cash_balance(
            builder=builder,
            run_context=context.run_context,
            run_mode="BACKTEST",
            prior_ledger=None,
            prior_portfolio=None,
        )

    assert replay_engine_module._drawdown_pct(
        peak_value=Decimal("0"),
        portfolio_value=Decimal("100"),
    ) == Decimal("0.0000000000")

    assert replay_engine_module._resolve_signal_reference_price(
        context=context,
        asset_id=1,
        side="SELL",
    ) == Decimal("99.000000000000000000")

    db.rows["order_book_snapshot"] = []
    db.rows["market_ohlcv_hourly"] = [
        {
            "asset_id": 1,
            "hour_ts_utc": hour,
            "close_price": Decimal("55.000000000000000000"),
            "row_hash": "u" * 64,
            "source_venue": "KRAKEN",
        }
    ]
    context_ohlcv = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)
    assert replay_engine_module._resolve_signal_reference_price(
        context=context_ohlcv,
        asset_id=1,
        side="BUY",
    ) == Decimal("55.000000000000000000")

    db.rows["market_ohlcv_hourly"] = []
    context_none = DeterministicContextBuilder(db).build_context(db.run_id, 1, "LIVE", hour)
    assert replay_engine_module._resolve_signal_reference_price(
        context=context_none,
        asset_id=1,
        side="BUY",
    ) is None


def test_derive_order_intent_emits_event_when_reference_price_missing() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    db.rows["order_book_snapshot"] = []
    db.rows["market_ohlcv_hourly"] = []
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

    intent, events = _derive_order_intent(
        context=context,
        writer=writer,
        signal=signal,
        severe_recovery_reason_code="NONE",
    )
    assert intent is None
    assert any(event.reason_code == "ORDER_REFERENCE_PRICE_UNAVAILABLE" for event in events)


def test_phase5_compare_helpers_cover_presence_and_hash_paths() -> None:
    db = _FakeDB()
    hour = db.rows["run_context"][0]["origin_hour_ts_utc"]
    result = execute_hour(db, db.run_id, 1, "LIVE", hour)

    expected_cash = result.cash_ledger_rows
    assert any(
        mismatch.field_name == "presence" and mismatch.actual == "stored_absent"
        for mismatch in replay_engine_module._compare_cash_ledger(expected_cash, [])
    )
    assert any(
        mismatch.field_name == "row_hash"
        for mismatch in replay_engine_module._compare_cash_ledger(
            expected_cash,
            [{"ledger_seq": expected_cash[0].ledger_seq, "row_hash": "0" * 64}],
        )
    )

    portfolio_expected = result.portfolio_hourly_states
    assert any(
        mismatch.actual == "stored_present"
        for mismatch in replay_engine_module._compare_portfolio_hourly_states(
            tuple(),
            [{"hour_ts_utc": portfolio_expected[0].hour_ts_utc, "row_hash": "0" * 64}],
        )
    )
    assert any(
        mismatch.actual == "stored_absent"
        for mismatch in replay_engine_module._compare_portfolio_hourly_states(
            portfolio_expected,
            tuple(),
        )
    )

    cluster_expected = result.cluster_exposure_hourly_states
    assert any(
        mismatch.actual == "stored_present"
        for mismatch in replay_engine_module._compare_cluster_exposure_hourly_states(
            tuple(),
            [{"cluster_id": cluster_expected[0].cluster_id, "row_hash": "0" * 64}],
        )
    )
    assert any(
        mismatch.actual == "stored_absent"
        for mismatch in replay_engine_module._compare_cluster_exposure_hourly_states(
            cluster_expected,
            tuple(),
        )
    )

    risk_expected = result.risk_hourly_states
    assert any(
        mismatch.actual == "stored_present"
        for mismatch in replay_engine_module._compare_risk_hourly_states(
            tuple(),
            [{"hour_ts_utc": risk_expected[0].hour_ts_utc, "row_hash": "0" * 64}],
        )
    )
    assert any(
        mismatch.actual == "stored_absent"
        for mismatch in replay_engine_module._compare_risk_hourly_states(
            risk_expected,
            tuple(),
        )
    )
