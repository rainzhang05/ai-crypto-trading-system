from __future__ import annotations

import builtins
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from execution.phase6.artifact_packager import _gather_files, commit_packaged_artifacts, package_promoted_artifacts
from execution.phase6.backtest_orchestrator import _simulate_fold_metric, run_phase6b_backtest
from execution.phase6.drift_monitor import DriftObservation, DriftThresholds, drift_triggered, persist_drift_event
from execution.phase6.hindcast_forecast import evaluate_forecast_metrics, persist_hindcast_forecast_metrics
from execution.phase6.promotion_gate import DEFAULT_THRESHOLDS, PromotionMetrics, evaluate_promotion, persist_promotion_decision
from execution.phase6.walk_forward import FoldWindow, generate_walk_forward_folds
from tests.phase6.utils import FakeDB


def test_walk_forward_generation_and_errors() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)
    with pytest.raises(RuntimeError, match="end_utc must be greater"):
        generate_walk_forward_folds(start_utc=end, end_utc=start, train_days=1, valid_days=1, step_days=1)
    with pytest.raises(RuntimeError, match="must be positive"):
        generate_walk_forward_folds(start_utc=start, end_utc=end, train_days=0, valid_days=1, step_days=1)
    with pytest.raises(RuntimeError, match="No walk-forward folds generated"):
        generate_walk_forward_folds(start_utc=start, end_utc=end, train_days=2, valid_days=2, step_days=1)

    folds = generate_walk_forward_folds(
        start_utc=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_utc=datetime(2026, 12, 31, tzinfo=timezone.utc),
        train_days=365,
        valid_days=30,
        step_days=30,
    )
    assert len(folds) >= 1
    assert folds[0].fold_hash


def test_backtest_simulation_and_persistence() -> None:
    fold = FoldWindow(
        fold_index=0,
        train_start_utc=datetime(2025, 1, 1, tzinfo=timezone.utc),
        train_end_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_start_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_end_utc=datetime(2026, 2, 1, tzinfo=timezone.utc),
        fold_hash="f1",
    )
    labeled_empty = pd.DataFrame(columns=["trade_ts_utc", "label_ret_H1"])
    metric_empty = _simulate_fold_metric(fold, labeled_empty)
    assert metric_empty.trades_count == 0

    labeled = pd.DataFrame(
        {
            "trade_ts_utc": [datetime(2026, 1, 2, tzinfo=timezone.utc), datetime(2026, 1, 3, tzinfo=timezone.utc)],
            "label_ret_H1": [0.01, -0.02],
        }
    )
    metric = _simulate_fold_metric(fold, labeled)
    assert metric.trades_count == 2

    db = FakeDB()
    result = run_phase6b_backtest(
        db=db,
        account_id=1,
        cost_profile_id=1,
        initial_capital=Decimal("1000"),
        strategy_code_sha="a" * 40,
        config_hash="cfg",
        universe_hash="uh",
        folds=(fold,),
        labeled_frame=labeled,
        random_seed=7,
    )
    assert result.fold_metrics[0].fold_index == 0
    assert len(db.executed) == 2


def test_forecast_metrics_and_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def _patched(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "numpy":
            raise ImportError("numpy")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _patched)
    with pytest.raises(RuntimeError, match="numpy is required"):
        evaluate_forecast_metrics(pd.DataFrame({"p": [0.1], "t": [0]}), "p", "t")
    monkeypatch.undo()

    with pytest.raises(RuntimeError, match="frame is empty"):
        evaluate_forecast_metrics(pd.DataFrame(columns=["p", "t"]), "p", "t")

    frame = pd.DataFrame({"p": [0.1, 0.7, 0.6], "t": [0, 1, 1]})
    metrics = evaluate_forecast_metrics(frame, "p", "t")
    assert Decimal("0") <= metrics.directional_accuracy <= Decimal("1")

    db = FakeDB()
    persist_hindcast_forecast_metrics(
        db,
        training_cycle_id="tc1",
        symbol="BTC",
        horizon="H1",
        metric_kind="ROLLING",
        metrics=metrics,
    )
    assert len(db.executed) == 1


def test_drift_and_promotion_logic_and_persistence() -> None:
    thresholds = DriftThresholds(accuracy_drop_pp=Decimal("5"), ece_delta=Decimal("0.03"), psi_threshold=Decimal("0.25"))
    observation_ok = DriftObservation(symbol="BTC", horizon="H1", accuracy_drop_pp=Decimal("1"), ece_delta=Decimal("0.01"), psi_value=Decimal("0.1"))
    observation_bad = DriftObservation(symbol="BTC", horizon="H1", accuracy_drop_pp=Decimal("5"), ece_delta=Decimal("0.01"), psi_value=Decimal("0.1"))
    assert drift_triggered(observation_ok, thresholds) is False
    assert drift_triggered(observation_bad, thresholds) is True

    db = FakeDB()
    assert persist_drift_event(db, training_cycle_ref="ref", observation=observation_ok, thresholds=thresholds) is False
    assert persist_drift_event(db, training_cycle_ref="ref", observation=observation_bad, thresholds=thresholds) is True
    assert len(db.executed) == 1

    metrics = PromotionMetrics(
        acc_h1=Decimal("0.6"),
        acc_h4=Decimal("0.6"),
        acc_h24=Decimal("0.6"),
        brier=Decimal("0.1"),
        ece=Decimal("0.01"),
        sharpe=Decimal("1.0"),
        max_drawdown=Decimal("0.1"),
        net_return=Decimal("0.01"),
    )
    decision = evaluate_promotion(metrics)
    assert decision.approved is True
    decision_id = persist_promotion_decision(
        db,
        training_cycle_id="tc1",
        candidate_model_set_hash="hash",
        decision=decision,
        metrics=metrics,
    )
    assert decision_id

    failing = evaluate_promotion(
        PromotionMetrics(
            acc_h1=Decimal("0.1"),
            acc_h4=Decimal("0.6"),
            acc_h24=Decimal("0.6"),
            brier=Decimal("0.1"),
            ece=Decimal("0.01"),
            sharpe=Decimal("1.0"),
            max_drawdown=Decimal("0.1"),
            net_return=Decimal("0.01"),
        ),
        thresholds=DEFAULT_THRESHOLDS,
    )
    assert failing.reason_code == "ACC_H1_BELOW_THRESHOLD"


@pytest.mark.parametrize(
    ("metrics", "reason"),
    [
        (
            PromotionMetrics(
                acc_h1=Decimal("0.6"),
                acc_h4=Decimal("0.1"),
                acc_h24=Decimal("0.6"),
                brier=Decimal("0.1"),
                ece=Decimal("0.01"),
                sharpe=Decimal("1.0"),
                max_drawdown=Decimal("0.1"),
                net_return=Decimal("0.01"),
            ),
            "ACC_H4_BELOW_THRESHOLD",
        ),
        (
            PromotionMetrics(
                acc_h1=Decimal("0.6"),
                acc_h4=Decimal("0.6"),
                acc_h24=Decimal("0.1"),
                brier=Decimal("0.1"),
                ece=Decimal("0.01"),
                sharpe=Decimal("1.0"),
                max_drawdown=Decimal("0.1"),
                net_return=Decimal("0.01"),
            ),
            "ACC_H24_BELOW_THRESHOLD",
        ),
        (
            PromotionMetrics(
                acc_h1=Decimal("0.6"),
                acc_h4=Decimal("0.6"),
                acc_h24=Decimal("0.6"),
                brier=Decimal("0.9"),
                ece=Decimal("0.01"),
                sharpe=Decimal("1.0"),
                max_drawdown=Decimal("0.1"),
                net_return=Decimal("0.01"),
            ),
            "BRIER_ABOVE_THRESHOLD",
        ),
        (
            PromotionMetrics(
                acc_h1=Decimal("0.6"),
                acc_h4=Decimal("0.6"),
                acc_h24=Decimal("0.6"),
                brier=Decimal("0.1"),
                ece=Decimal("0.9"),
                sharpe=Decimal("1.0"),
                max_drawdown=Decimal("0.1"),
                net_return=Decimal("0.01"),
            ),
            "ECE_ABOVE_THRESHOLD",
        ),
        (
            PromotionMetrics(
                acc_h1=Decimal("0.6"),
                acc_h4=Decimal("0.6"),
                acc_h24=Decimal("0.6"),
                brier=Decimal("0.1"),
                ece=Decimal("0.01"),
                sharpe=Decimal("0.1"),
                max_drawdown=Decimal("0.1"),
                net_return=Decimal("0.01"),
            ),
            "SHARPE_BELOW_THRESHOLD",
        ),
        (
            PromotionMetrics(
                acc_h1=Decimal("0.6"),
                acc_h4=Decimal("0.6"),
                acc_h24=Decimal("0.6"),
                brier=Decimal("0.1"),
                ece=Decimal("0.01"),
                sharpe=Decimal("1.0"),
                max_drawdown=Decimal("0.9"),
                net_return=Decimal("0.01"),
            ),
            "DRAWDOWN_ABOVE_THRESHOLD",
        ),
        (
            PromotionMetrics(
                acc_h1=Decimal("0.6"),
                acc_h4=Decimal("0.6"),
                acc_h24=Decimal("0.6"),
                brier=Decimal("0.1"),
                ece=Decimal("0.01"),
                sharpe=Decimal("1.0"),
                max_drawdown=Decimal("0.1"),
                net_return=Decimal("0"),
            ),
            "NET_RETURN_NOT_POSITIVE",
        ),
    ],
)
def test_promotion_failure_reasons(metrics: PromotionMetrics, reason: str) -> None:
    decision = evaluate_promotion(metrics)
    assert decision.approved is False
    assert decision.reason_code == reason


def test_artifact_packager_and_commit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="No artifact files"):
        _gather_files((tmp_path / "missing.bin",))

    model_a = tmp_path / "a.bin"
    model_b = tmp_path / "b.bin"
    model_a.write_text("a", encoding="utf-8")
    model_b.write_text("b", encoding="utf-8")

    result = package_promoted_artifacts(
        promotion_id="promo1",
        output_root=tmp_path / "bundles",
        model_files=(model_a, model_b, tmp_path / "skip_dir"),
        compatibility_range=">=1,<2",
        source_ref="local",
    )
    assert result.bundle_dir.exists()
    assert result.manifest_path.exists()
    assert result.report_path.exists()
    assert result.artifact_hash

    calls: list[list[str]] = []

    def _run(cmd, cwd, check):  # type: ignore[no-untyped-def]
        assert check is True
        calls.append(list(cmd))
        return None

    monkeypatch.setattr("execution.phase6.artifact_packager.subprocess.run", _run)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    artifact = repo_root / "artifacts" / "model_bundles" / "promo1" / "bundle_manifest.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}", encoding="utf-8")

    commit_packaged_artifacts(
        repo_root=repo_root,
        branch_name="automation/phase6-promotions",
        files_to_commit=(artifact,),
        commit_message="phase6: promotion promo1",
    )
    assert calls[0][:3] == ["git", "checkout", "-B"]
    assert calls[1][0:2] == ["git", "add"]
    assert calls[2][0:2] == ["git", "commit"]
