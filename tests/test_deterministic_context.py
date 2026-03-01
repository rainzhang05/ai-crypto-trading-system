"""Unit tests for deterministic context construction and validation."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID

import pytest

from execution.deterministic_context import DeterministicAbortError, DeterministicContextBuilder


class _FakeDB:
    def __init__(self, payload: dict[str, list[dict[str, Any]]]) -> None:
        self.payload = payload

    def fetch_one(self, sql: str, params: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        rows = self.fetch_all(sql, params)
        return rows[0] if rows else None

    def fetch_all(self, sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        q = " ".join(sql.lower().split())
        if "from run_context" in q:
            return list(self.payload.get("run_context", []))
        if "from model_prediction" in q:
            return list(self.payload.get("model_prediction", []))
        if "from regime_output" in q:
            return list(self.payload.get("regime_output", []))
        if "from risk_hourly_state" in q:
            return list(self.payload.get("risk_hourly_state", []))
        if "from portfolio_hourly_state" in q:
            return list(self.payload.get("portfolio_hourly_state", []))
        if "from cluster_exposure_hourly_state" in q:
            return list(self.payload.get("cluster_exposure_hourly_state", []))
        if "from cash_ledger" in q:
            return list(self.payload.get("cash_ledger", []))
        if "from model_training_window" in q:
            rows = list(self.payload.get("model_training_window", []))
            if "where training_window_id" in q:
                target = params.get("training_window_id")
                return [row for row in rows if row["training_window_id"] == target]
            return rows
        if "from model_activation_gate" in q:
            rows = list(self.payload.get("model_activation_gate", []))
            if "where activation_id" in q:
                target = params.get("activation_id")
                return [row for row in rows if row["activation_id"] == target]
            return rows
        if "from asset_cluster_membership" in q:
            return list(self.payload.get("asset_cluster_membership", []))
        if "from cost_profile" in q:
            return list(self.payload.get("cost_profile", []))
        raise RuntimeError(f"Unhandled query: {sql}")


def _live_payload() -> dict[str, list[dict[str, Any]]]:
    run_id = UUID("11111111-1111-4111-8111-111111111111")
    hour = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return {
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
                "model_version_id": 22,
                "expected_return": Decimal("0.02"),
                "upstream_hash": "d" * 64,
                "row_hash": "e" * 64,
                "training_window_id": None,
                "lineage_backtest_run_id": None,
                "lineage_fold_index": None,
                "lineage_horizon": None,
                "activation_id": 7,
            }
        ],
        "regime_output": [
            {
                "run_id": run_id,
                "account_id": 1,
                "run_mode": "LIVE",
                "asset_id": 1,
                "hour_ts_utc": hour,
                "model_version_id": 22,
                "regime_label": "TRENDING",
                "upstream_hash": "f" * 64,
                "row_hash": "1" * 64,
                "training_window_id": None,
                "lineage_backtest_run_id": None,
                "lineage_fold_index": None,
                "lineage_horizon": None,
                "activation_id": 7,
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
                "state_hash": "2" * 64,
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
                "row_hash": "3" * 64,
            }
        ],
        "cluster_exposure_hourly_state": [
            {
                "run_mode": "LIVE",
                "account_id": 1,
                "cluster_id": 9,
                "hour_ts_utc": hour,
                "source_run_id": run_id,
                "exposure_pct": Decimal("0.01"),
                "max_cluster_exposure_pct": Decimal("0.08"),
                "state_hash": "4" * 64,
                "parent_risk_hash": "r" * 64,
                "row_hash": "5" * 64,
            }
        ],
        "model_activation_gate": [
            {
                "activation_id": 7,
                "model_version_id": 22,
                "run_mode": "LIVE",
                "validation_window_end_utc": hour - timedelta(hours=1),
                "status": "APPROVED",
                "approval_hash": "6" * 64,
            }
        ],
        "asset_cluster_membership": [
            {
                "membership_id": 100,
                "asset_id": 1,
                "cluster_id": 9,
                "membership_hash": "7" * 64,
                "effective_from_utc": hour - timedelta(days=1),
            }
        ],
        "cost_profile": [
            {
                "cost_profile_id": 2,
                "fee_rate": Decimal("0.004"),
                "slippage_param_hash": "8" * 64,
            }
        ],
        "cash_ledger": [],
        "model_training_window": [],
    }


def _backtest_leak_payload() -> dict[str, list[dict[str, Any]]]:
    payload = _live_payload()
    run_id = payload["run_context"][0]["run_id"]
    hour = payload["run_context"][0]["hour_ts_utc"]
    payload["run_context"][0]["run_mode"] = "BACKTEST"
    payload["model_prediction"][0].update(
        {
            "run_mode": "BACKTEST",
            "activation_id": None,
            "training_window_id": 99,
            "lineage_backtest_run_id": run_id,
            "lineage_fold_index": 0,
            "lineage_horizon": "H1",
        }
    )
    payload["regime_output"][0].update(
        {
            "run_mode": "BACKTEST",
            "activation_id": None,
            "training_window_id": 99,
            "lineage_backtest_run_id": run_id,
            "lineage_fold_index": 0,
            "lineage_horizon": "H1",
        }
    )
    payload["model_activation_gate"] = []
    payload["model_training_window"] = [
        {
            "training_window_id": 99,
            "backtest_run_id": run_id,
            "model_version_id": 22,
            "fold_index": 0,
            "horizon": "H1",
            "train_end_utc": hour,  # leakage: prediction hour <= train_end_utc
            "valid_start_utc": hour - timedelta(hours=1),
            "valid_end_utc": hour + timedelta(hours=1),
            "training_window_hash": "9" * 64,
            "row_hash": "a" * 64,
        }
    ]
    return payload


def test_build_context_live_success() -> None:
    payload = _live_payload()
    builder = DeterministicContextBuilder(_FakeDB(payload))
    context = builder.build_context(
        run_id=payload["run_context"][0]["run_id"],
        account_id=1,
        run_mode="LIVE",
        hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
    )
    assert context.run_context.run_mode == "LIVE"
    assert len(context.predictions) == 1
    assert len(context.regimes) == 1
    assert context.find_membership(1) is not None


def test_build_context_backtest_walk_forward_leakage_aborts() -> None:
    payload = _backtest_leak_payload()
    builder = DeterministicContextBuilder(_FakeDB(payload))
    with pytest.raises(DeterministicAbortError, match="leaks into training period"):
        builder.build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="BACKTEST",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )


def test_missing_run_context_aborts() -> None:
    payload = _live_payload()
    payload["run_context"] = []
    builder = DeterministicContextBuilder(_FakeDB(payload))
    with pytest.raises(DeterministicAbortError, match="run_context row not found"):
        builder.build_context(
            run_id=UUID("11111111-1111-4111-8111-111111111111"),
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_live_prediction_missing_activation_record_aborts() -> None:
    payload = _live_payload()
    payload["model_activation_gate"] = []
    builder = DeterministicContextBuilder(_FakeDB(payload))
    with pytest.raises(DeterministicAbortError, match="activation_id=7 not found"):
        builder.build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )


def test_backtest_training_window_missing_aborts() -> None:
    payload = _backtest_leak_payload()
    payload["model_training_window"] = []
    payload["model_prediction"][0]["hour_ts_utc"] = payload["run_context"][0]["hour_ts_utc"] + timedelta(hours=1)
    payload["regime_output"][0]["hour_ts_utc"] = payload["run_context"][0]["hour_ts_utc"] + timedelta(hours=1)
    builder = DeterministicContextBuilder(_FakeDB(payload))
    with pytest.raises(DeterministicAbortError, match="training_window_id=99 not found"):
        builder.build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="BACKTEST",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )


def test_cluster_parent_risk_lineage_mismatch_aborts() -> None:
    payload = _live_payload()
    payload["cluster_exposure_hourly_state"][0]["parent_risk_hash"] = "x" * 64
    builder = DeterministicContextBuilder(_FakeDB(payload))
    with pytest.raises(DeterministicAbortError, match="Cluster parent_risk_hash lineage mismatch"):
        builder.build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )


def test_missing_membership_for_prediction_aborts() -> None:
    payload = _live_payload()
    payload["asset_cluster_membership"] = []
    builder = DeterministicContextBuilder(_FakeDB(payload))
    with pytest.raises(DeterministicAbortError, match="Missing asset_cluster_membership"):
        builder.build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )


def test_prior_ledger_hash_continuity_break_aborts() -> None:
    payload = _live_payload()
    hour = payload["run_context"][0]["hour_ts_utc"]
    payload["cash_ledger"] = [
        {
            "ledger_seq": 2,
            "balance_before": Decimal("100"),
            "balance_after": Decimal("110"),
            "prev_ledger_hash": None,
            "ledger_hash": "z" * 64,
            "row_hash": "y" * 64,
            "event_ts_utc": hour - timedelta(hours=1),
        }
    ]
    builder = DeterministicContextBuilder(_FakeDB(payload))
    with pytest.raises(DeterministicAbortError, match="broken ledger hash continuity"):
        builder.build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )


def test_live_regime_not_approved_aborts() -> None:
    payload = _live_payload()
    payload["model_activation_gate"][0]["status"] = "REVOKED"
    builder = DeterministicContextBuilder(_FakeDB(deepcopy(payload)))
    with pytest.raises(DeterministicAbortError, match="activation not APPROVED"):
        builder.build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )
