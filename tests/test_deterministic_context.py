"""Unit tests for deterministic context construction and validation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID

import pytest

from execution import deterministic_context as deterministic_context_module
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


def _backtest_valid_payload() -> dict[str, list[dict[str, Any]]]:
    payload = _backtest_leak_payload()
    hour = payload["run_context"][0]["hour_ts_utc"]
    payload["model_training_window"][0]["train_end_utc"] = hour - timedelta(hours=2)
    payload["model_training_window"][0]["valid_start_utc"] = hour - timedelta(hours=1)
    payload["model_training_window"][0]["valid_end_utc"] = hour + timedelta(hours=1)
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


def test_context_find_methods_return_none_when_absent() -> None:
    payload = _live_payload()
    context = DeterministicContextBuilder(_FakeDB(payload)).build_context(
        run_id=payload["run_context"][0]["run_id"],
        account_id=1,
        run_mode="LIVE",
        hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
    )
    assert context.find_training_window(999) is None
    assert context.find_activation(999) is None
    assert context.find_regime(asset_id=999, model_version_id=999) is None
    assert context.find_membership(asset_id=999) is None
    assert context.find_cluster_state(cluster_id=999) is None


def test_context_no_predictions_aborts() -> None:
    payload = _live_payload()
    payload["model_prediction"] = []
    with pytest.raises(DeterministicAbortError, match="No model_prediction rows"):
        DeterministicContextBuilder(_FakeDB(payload)).build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )


def test_context_no_regimes_aborts() -> None:
    payload = _live_payload()
    payload["regime_output"] = []
    with pytest.raises(DeterministicAbortError, match="No regime_output rows"):
        DeterministicContextBuilder(_FakeDB(payload)).build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )


def test_context_risk_source_run_mismatch_aborts() -> None:
    payload = _live_payload()
    payload["risk_hourly_state"][0]["source_run_id"] = UUID("22222222-2222-4222-8222-222222222222")
    with pytest.raises(DeterministicAbortError, match="Risk state source_run_id mismatch"):
        DeterministicContextBuilder(_FakeDB(payload)).build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )


def test_context_capital_source_run_mismatch_aborts() -> None:
    payload = _live_payload()
    payload["portfolio_hourly_state"][0]["source_run_id"] = UUID("22222222-2222-4222-8222-222222222222")
    with pytest.raises(DeterministicAbortError, match="Capital state source_run_id mismatch"):
        DeterministicContextBuilder(_FakeDB(payload)).build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )


def test_context_risk_capital_cross_account_aborts() -> None:
    payload = _live_payload()
    payload["risk_hourly_state"][0]["account_id"] = 2
    with pytest.raises(DeterministicAbortError, match="Cross-account contamination on risk/capital state"):
        DeterministicContextBuilder(_FakeDB(payload)).build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )


def test_context_cluster_cross_account_aborts() -> None:
    payload = _live_payload()
    payload["cluster_exposure_hourly_state"][0]["account_id"] = 2
    with pytest.raises(DeterministicAbortError, match="Cross-account contamination in cluster_exposure_hourly_state"):
        DeterministicContextBuilder(_FakeDB(payload)).build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )


def test_context_prediction_cross_account_aborts() -> None:
    payload = _live_payload()
    payload["model_prediction"][0]["account_id"] = 2
    with pytest.raises(DeterministicAbortError, match="Cross-account contamination in model_prediction"):
        DeterministicContextBuilder(_FakeDB(payload)).build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )


def test_context_prediction_mode_mismatch_aborts() -> None:
    payload = _live_payload()
    payload["model_prediction"][0]["run_mode"] = "PAPER"
    with pytest.raises(DeterministicAbortError, match="model_prediction run_mode mismatch"):
        DeterministicContextBuilder(_FakeDB(payload)).build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )


def test_context_regime_cross_account_aborts() -> None:
    payload = _live_payload()
    payload["regime_output"][0]["account_id"] = 2
    with pytest.raises(DeterministicAbortError, match="Cross-account contamination in regime_output"):
        DeterministicContextBuilder(_FakeDB(payload)).build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )


def test_context_regime_mode_mismatch_aborts() -> None:
    payload = _live_payload()
    payload["regime_output"][0]["run_mode"] = "PAPER"
    with pytest.raises(DeterministicAbortError, match="regime_output run_mode mismatch"):
        DeterministicContextBuilder(_FakeDB(payload)).build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )


def test_context_missing_regime_for_prediction_aborts() -> None:
    payload = _live_payload()
    payload["regime_output"][0]["asset_id"] = 999
    with pytest.raises(DeterministicAbortError, match="Missing regime_output for asset_id=1 model_version_id=22"):
        DeterministicContextBuilder(_FakeDB(payload)).build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )


def test_backtest_prediction_lineage_mismatch_branches() -> None:
    payload = _backtest_valid_payload()
    checks = [
        ("training_window_id", None, "BACKTEST prediction missing training_window_id"),
        ("lineage_backtest_run_id", UUID("33333333-3333-4333-8333-333333333333"), "lineage_backtest_run_id mismatch"),
        ("lineage_fold_index", 99, "lineage_fold_index mismatch"),
        ("lineage_horizon", "H2", "lineage_horizon mismatch"),
        ("model_version_id", 999, "model_version_id mismatch in lineage"),
    ]
    for field, value, msg in checks:
        p = deepcopy(payload)
        p["model_prediction"][0][field] = value
        with pytest.raises(DeterministicAbortError, match=msg):
            DeterministicContextBuilder(_FakeDB(p)).build_context(
                run_id=p["run_context"][0]["run_id"],
                account_id=1,
                run_mode="BACKTEST",
                hour_ts_utc=p["run_context"][0]["origin_hour_ts_utc"],
            )


def test_backtest_prediction_window_and_activation_branches() -> None:
    payload = _backtest_valid_payload()
    hour = payload["run_context"][0]["hour_ts_utc"]

    p_before_valid = deepcopy(payload)
    p_before_valid["model_training_window"][0]["valid_start_utc"] = hour + timedelta(hours=1)
    with pytest.raises(DeterministicAbortError, match="before validation window"):
        DeterministicContextBuilder(_FakeDB(p_before_valid)).build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="BACKTEST",
            hour_ts_utc=hour,
        )

    p_after_valid = deepcopy(payload)
    p_after_valid["model_training_window"][0]["valid_end_utc"] = hour
    with pytest.raises(DeterministicAbortError, match="after validation window"):
        DeterministicContextBuilder(_FakeDB(p_after_valid)).build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="BACKTEST",
            hour_ts_utc=hour,
        )

    p_activation = deepcopy(payload)
    p_activation["model_prediction"][0]["activation_id"] = 7
    p_activation["model_activation_gate"] = [
        {
            "activation_id": 7,
            "model_version_id": 22,
            "run_mode": "BACKTEST",
            "validation_window_end_utc": hour - timedelta(hours=1),
            "status": "APPROVED",
            "approval_hash": "9" * 64,
        }
    ]
    with pytest.raises(DeterministicAbortError, match="must not carry activation_id"):
        DeterministicContextBuilder(_FakeDB(p_activation)).build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="BACKTEST",
            hour_ts_utc=hour,
        )


def test_backtest_regime_lineage_branches() -> None:
    payload = _backtest_valid_payload()
    checks = [
        ("training_window_id", None, "BACKTEST regime_output missing training_window_id"),
        ("lineage_backtest_run_id", UUID("33333333-3333-4333-8333-333333333333"), "lineage_backtest_run_id mismatch"),
        ("lineage_fold_index", 99, "lineage_fold_index mismatch"),
        ("lineage_horizon", "H2", "lineage_horizon mismatch"),
        ("model_version_id", 999, "model_version_id mismatch in lineage"),
    ]
    for field, value, msg in checks:
        p = deepcopy(payload)
        p["regime_output"][0][field] = value
        with pytest.raises(DeterministicAbortError, match=msg):
            DeterministicContextBuilder(_FakeDB(p)).build_context(
                run_id=p["run_context"][0]["run_id"],
                account_id=1,
                run_mode="BACKTEST",
                hour_ts_utc=p["run_context"][0]["origin_hour_ts_utc"],
            )


def test_backtest_regime_window_and_activation_branches() -> None:
    payload = _backtest_valid_payload()
    hour = payload["run_context"][0]["hour_ts_utc"]
    builder = DeterministicContextBuilder(_FakeDB(payload))
    context = builder.build_context(
        run_id=payload["run_context"][0]["run_id"],
        account_id=1,
        run_mode="BACKTEST",
        hour_ts_utc=hour,
    )
    regime = context.regimes[0]
    window = context.training_windows[0]

    with pytest.raises(DeterministicAbortError, match="training window not found"):
        builder._validate_regime_lineage(replace(regime, training_window_id=999), context)

    with pytest.raises(DeterministicAbortError, match="regime_output leaks into training period"):
        bad_window = replace(window, train_end_utc=hour)
        builder._validate_regime_lineage(regime, replace(context, training_windows=(bad_window,)))

    with pytest.raises(DeterministicAbortError, match="regime_output before validation window"):
        bad_window = replace(window, valid_start_utc=hour + timedelta(hours=1))
        builder._validate_regime_lineage(regime, replace(context, training_windows=(bad_window,)))

    with pytest.raises(DeterministicAbortError, match="regime_output after validation window"):
        bad_window = replace(window, valid_end_utc=hour)
        builder._validate_regime_lineage(regime, replace(context, training_windows=(bad_window,)))

    with pytest.raises(DeterministicAbortError, match="regime_output must not carry activation_id"):
        builder._validate_regime_lineage(replace(regime, activation_id=7), context)


def test_live_prediction_and_regime_activation_mismatch_branches() -> None:
    payload = _live_payload()
    context = DeterministicContextBuilder(_FakeDB(payload)).build_context(
        run_id=payload["run_context"][0]["run_id"],
        account_id=1,
        run_mode="LIVE",
        hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
    )
    builder = DeterministicContextBuilder(_FakeDB(payload))
    prediction = context.predictions[0]
    regime = context.regimes[0]

    with pytest.raises(DeterministicAbortError, match="LIVE/PAPER prediction missing activation_id"):
        builder._validate_prediction_lineage(replace(prediction, activation_id=None), context)
    with pytest.raises(DeterministicAbortError, match="prediction activation record missing"):
        builder._validate_prediction_lineage(prediction, replace(context, activation_records=tuple()))
    with pytest.raises(DeterministicAbortError, match="prediction activation model_version mismatch"):
        bad_activation = replace(context.activation_records[0], model_version_id=999)
        builder._validate_prediction_lineage(prediction, replace(context, activation_records=(bad_activation,)))
    with pytest.raises(DeterministicAbortError, match="prediction activation run_mode mismatch"):
        bad_mode = replace(context.activation_records[0], run_mode="PAPER")
        builder._validate_prediction_lineage(prediction, replace(context, activation_records=(bad_mode,)))

    with pytest.raises(DeterministicAbortError, match="LIVE/PAPER regime_output missing activation_id"):
        builder._validate_regime_lineage(replace(regime, activation_id=None), context)
    with pytest.raises(DeterministicAbortError, match="regime_output activation record missing"):
        builder._validate_regime_lineage(regime, replace(context, activation_records=tuple()))
    with pytest.raises(DeterministicAbortError, match="regime_output activation not APPROVED"):
        revoked = replace(context.activation_records[0], status="REVOKED")
        builder._validate_regime_lineage(regime, replace(context, activation_records=(revoked,)))
    with pytest.raises(DeterministicAbortError, match="regime_output activation model_version mismatch"):
        bad_activation = replace(context.activation_records[0], model_version_id=999)
        builder._validate_regime_lineage(regime, replace(context, activation_records=(bad_activation,)))
    with pytest.raises(DeterministicAbortError, match="regime_output activation run_mode mismatch"):
        bad_mode = replace(context.activation_records[0], run_mode="PAPER")
        builder._validate_regime_lineage(regime, replace(context, activation_records=(bad_mode,)))


def test_backtest_prediction_training_window_not_found_branch() -> None:
    payload = _backtest_valid_payload()
    hour = payload["run_context"][0]["hour_ts_utc"]
    builder = DeterministicContextBuilder(_FakeDB(payload))
    context = builder.build_context(
        run_id=payload["run_context"][0]["run_id"],
        account_id=1,
        run_mode="BACKTEST",
        hour_ts_utc=hour,
    )
    with pytest.raises(DeterministicAbortError, match="prediction training window not found"):
        builder._validate_prediction_lineage(context.predictions[0], replace(context, training_windows=tuple()))


def test_context_missing_risk_or_capital_or_cost_profile_aborts() -> None:
    payload = _live_payload()
    p = deepcopy(payload)
    p["risk_hourly_state"] = []
    with pytest.raises(DeterministicAbortError, match="risk_hourly_state row not found"):
        DeterministicContextBuilder(_FakeDB(p)).build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )

    p = deepcopy(payload)
    p["portfolio_hourly_state"] = []
    with pytest.raises(DeterministicAbortError, match="portfolio_hourly_state row not found"):
        DeterministicContextBuilder(_FakeDB(p)).build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )

    p = deepcopy(payload)
    p["cost_profile"] = []
    with pytest.raises(DeterministicAbortError, match="No active KRAKEN cost_profile"):
        DeterministicContextBuilder(_FakeDB(p)).build_context(
            run_id=payload["run_context"][0]["run_id"],
            account_id=1,
            run_mode="LIVE",
            hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
        )


def test_context_training_and_activation_collectors_cover_regime_only_ids() -> None:
    payload = _live_payload()
    builder = DeterministicContextBuilder(_FakeDB(payload))

    prediction = replace(builder._load_predictions(payload["run_context"][0]["run_id"], 1, "LIVE", payload["run_context"][0]["origin_hour_ts_utc"])[0], training_window_id=None, activation_id=None)
    regime_only_window = replace(
        builder._load_regimes(payload["run_context"][0]["run_id"], 1, "LIVE", payload["run_context"][0]["origin_hour_ts_utc"])[0],
        training_window_id=99,
        activation_id=7,
    )

    payload["model_training_window"] = [
        {
            "training_window_id": 99,
            "backtest_run_id": payload["run_context"][0]["run_id"],
            "model_version_id": 22,
            "fold_index": 0,
            "horizon": "H1",
            "train_end_utc": payload["run_context"][0]["hour_ts_utc"] - timedelta(hours=2),
            "valid_start_utc": payload["run_context"][0]["hour_ts_utc"] - timedelta(hours=1),
            "valid_end_utc": payload["run_context"][0]["hour_ts_utc"] + timedelta(hours=1),
            "training_window_hash": "w" * 64,
            "row_hash": "x" * 64,
        }
    ]

    windows = builder._load_training_windows((prediction,), (regime_only_window,))
    assert len(windows) == 1
    activations = builder._load_activation_records((prediction,), (regime_only_window,))
    assert len(activations) == 1


def test_context_membership_loader_empty_and_duplicate_paths() -> None:
    payload = _live_payload()
    builder = DeterministicContextBuilder(_FakeDB(payload))
    assert builder._load_memberships(tuple(), payload["run_context"][0]["hour_ts_utc"]) == tuple()

    payload = _live_payload()
    payload["asset_cluster_membership"] = [
        {
            "membership_id": 200,
            "asset_id": 1,
            "cluster_id": 9,
            "membership_hash": "a" * 64,
            "effective_from_utc": payload["run_context"][0]["hour_ts_utc"] - timedelta(hours=1),
        },
        {
            "membership_id": 100,
            "asset_id": 1,
            "cluster_id": 9,
            "membership_hash": "b" * 64,
            "effective_from_utc": payload["run_context"][0]["hour_ts_utc"] - timedelta(days=1),
        },
        {
            "membership_id": 300,
            "asset_id": 999,
            "cluster_id": 9,
            "membership_hash": "c" * 64,
            "effective_from_utc": payload["run_context"][0]["hour_ts_utc"] - timedelta(minutes=30),
        },
    ]
    context = DeterministicContextBuilder(_FakeDB(payload)).build_context(
        run_id=payload["run_context"][0]["run_id"],
        account_id=1,
        run_mode="LIVE",
        hour_ts_utc=payload["run_context"][0]["origin_hour_ts_utc"],
    )
    assert context.memberships[0].membership_id == 200


def test_context_type_coercion_from_string_rows() -> None:
    payload = _live_payload()
    hour_iso = payload["run_context"][0]["hour_ts_utc"].isoformat()
    run_id_str = str(payload["run_context"][0]["run_id"])
    payload["run_context"][0]["run_id"] = run_id_str
    payload["run_context"][0]["hour_ts_utc"] = hour_iso
    payload["run_context"][0]["origin_hour_ts_utc"] = hour_iso
    payload["model_prediction"][0]["run_id"] = run_id_str
    payload["model_prediction"][0]["hour_ts_utc"] = hour_iso
    payload["model_prediction"][0]["expected_return"] = "0.02"
    payload["regime_output"][0]["run_id"] = run_id_str
    payload["regime_output"][0]["hour_ts_utc"] = hour_iso
    payload["risk_hourly_state"][0]["source_run_id"] = run_id_str
    payload["risk_hourly_state"][0]["hour_ts_utc"] = hour_iso
    payload["risk_hourly_state"][0]["portfolio_value"] = "10000"
    payload["portfolio_hourly_state"][0]["source_run_id"] = run_id_str
    payload["portfolio_hourly_state"][0]["hour_ts_utc"] = hour_iso
    payload["portfolio_hourly_state"][0]["cash_balance"] = "10000"
    payload["cluster_exposure_hourly_state"][0]["source_run_id"] = run_id_str
    payload["cluster_exposure_hourly_state"][0]["hour_ts_utc"] = hour_iso
    payload["model_activation_gate"][0]["validation_window_end_utc"] = (
        payload["run_context"][0]["hour_ts_utc"] if isinstance(payload["run_context"][0]["hour_ts_utc"], datetime)
        else datetime.fromisoformat(hour_iso) - timedelta(hours=1)
    ).isoformat()

    context = DeterministicContextBuilder(_FakeDB(payload)).build_context(
        run_id=UUID(run_id_str),
        account_id=1,
        run_mode="LIVE",
        hour_ts_utc=datetime.fromisoformat(hour_iso),
    )
    assert isinstance(context.run_context.run_id, UUID)
    assert isinstance(context.run_context.origin_hour_ts_utc, datetime)
    assert isinstance(context.predictions[0].expected_return, Decimal)


def test_context_scalar_coercion_helpers_from_strings() -> None:
    assert deterministic_context_module._as_decimal("1.25") == Decimal("1.25")
    parsed_dt = deterministic_context_module._as_datetime("2026-01-01T00:00:00+00:00")
    assert isinstance(parsed_dt, datetime)
    parsed_uuid = deterministic_context_module._as_uuid("11111111-1111-4111-8111-111111111111")
    assert isinstance(parsed_uuid, UUID)
