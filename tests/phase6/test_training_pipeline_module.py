from __future__ import annotations

import builtins
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from execution.phase6 import training_pipeline
from execution.phase6.promotion_gate import PromotionDecision
from tests.phase6.utils import FakeDB


def _base_labels_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["BTC", "BTC"],
            "trade_ts_utc": [
                datetime(2024, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            ],
            "label_ret_H1": [0.1, 0.2],
            "label_ret_H4": [0.1, 0.2],
            "label_ret_H24": [0.1, 0.2],
        }
    )


def test_create_and_complete_cycle_helpers() -> None:
    db = FakeDB()
    cycle_id, _started = training_pipeline._create_training_cycle(db, cycle_kind="SCHEDULED")
    assert cycle_id
    assert len(db.executed) == 1

    training_pipeline._complete_training_cycle(db, cycle_id=cycle_id, status="COMPLETED", detail_tokens=("x", 1))
    assert len(db.executed) == 2


def test_run_training_cycle_import_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    original_import = builtins.__import__

    def _patched(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "pandas":
            raise ImportError("pandas")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _patched)
    with pytest.raises(RuntimeError, match="pandas is required"):
        training_pipeline.run_training_cycle(
            db=FakeDB(),
            symbols=("BTC",),
            local_cache_dir=tmp_path,
            output_root=tmp_path / "out",
            account_id=1,
            cost_profile_id=1,
            strategy_code_sha="a" * 40,
            config_hash="cfg",
            universe_hash="univ",
            random_seed=7,
            cycle_kind="MANUAL",
        )


def _stub_cycle_dependencies(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, approved: bool) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    dataset_path = tmp_path / "dataset.parquet"
    pd.DataFrame({"x": [1]}).to_parquet(dataset_path, index=False)
    labels = _base_labels_frame()

    monkeypatch.setattr(
        training_pipeline,
        "materialize_tick_canonical_dataset",
        lambda **_kwargs: SimpleNamespace(dataset_snapshot_id="ds1", dataset_hash="dh1", output_path=dataset_path),
    )
    monkeypatch.setattr(training_pipeline, "build_tick_features", lambda _dataset: SimpleNamespace(frame=pd.DataFrame({"x": [1]})))
    monkeypatch.setattr(training_pipeline, "build_horizon_labels", lambda _frame: SimpleNamespace(frame=labels))
    monkeypatch.setattr(
        training_pipeline,
        "train_tree_specialists",
        lambda **_kwargs: (SimpleNamespace(artifact_path=tmp_path / "tree.joblib"),),
    )
    monkeypatch.setattr(
        training_pipeline,
        "train_deep_specialists",
        lambda **_kwargs: (SimpleNamespace(artifact_path=tmp_path / "deep.pt"),),
    )
    monkeypatch.setattr(
        training_pipeline,
        "train_regime_classifier",
        lambda **_kwargs: SimpleNamespace(artifact_path=tmp_path / "regime.joblib"),
    )
    monkeypatch.setattr(
        training_pipeline,
        "train_meta_ensemble",
        lambda **_kwargs: SimpleNamespace(artifact_path=tmp_path / "meta.joblib"),
    )
    monkeypatch.setattr(
        training_pipeline,
        "generate_walk_forward_folds",
        lambda **_kwargs: (
            SimpleNamespace(
                fold_index=0,
                train_start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
                train_end_utc=datetime(2025, 1, 1, tzinfo=timezone.utc),
                valid_start_utc=datetime(2025, 1, 1, tzinfo=timezone.utc),
                valid_end_utc=datetime(2025, 2, 1, tzinfo=timezone.utc),
                fold_hash="f1",
            ),
        ),
    )
    monkeypatch.setattr(
        training_pipeline,
        "run_phase6b_backtest",
        lambda **_kwargs: SimpleNamespace(
            fold_metrics=(
                SimpleNamespace(sharpe=Decimal("1"), max_drawdown_pct=Decimal("0.1"), net_return_pct=Decimal("0.2")),
            )
        ),
    )
    monkeypatch.setattr(
        training_pipeline,
        "evaluate_forecast_metrics",
        lambda _frame, _prob_col, _target_col: SimpleNamespace(
            directional_accuracy=Decimal("0.7"),
            brier_score=Decimal("0.1"),
            ece=Decimal("0.01"),
        ),
    )
    monkeypatch.setattr(training_pipeline, "persist_hindcast_forecast_metrics", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        training_pipeline,
        "evaluate_promotion",
        lambda _metrics: PromotionDecision(approved=approved, reason_code="APPROVED" if approved else "REJECTED"),
    )
    monkeypatch.setattr(training_pipeline, "persist_promotion_decision", lambda *_args, **_kwargs: "pd1")


def test_run_training_cycle_approved_and_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = FakeDB()
    _stub_cycle_dependencies(monkeypatch, tmp_path, approved=True)
    result = training_pipeline.run_training_cycle(
        db=db,
        symbols=("BTC",),
        local_cache_dir=tmp_path,
        output_root=tmp_path / "out",
        account_id=1,
        cost_profile_id=1,
        strategy_code_sha="a" * 40,
        config_hash="cfg",
        universe_hash="univ",
        random_seed=7,
        cycle_kind="MANUAL",
    )
    assert result.approved is True
    assert result.reason_code == "APPROVED"
    assert len(db.executed) >= 3

    db_reject = FakeDB()
    _stub_cycle_dependencies(monkeypatch, tmp_path / "r2", approved=False)
    result_reject = training_pipeline.run_training_cycle(
        db=db_reject,
        symbols=("BTC",),
        local_cache_dir=tmp_path,
        output_root=tmp_path / "out2",
        account_id=1,
        cost_profile_id=1,
        strategy_code_sha="a" * 40,
        config_hash="cfg",
        universe_hash="univ",
        random_seed=7,
        cycle_kind="MANUAL",
    )
    assert result_reject.approved is False
    assert result_reject.reason_code == "REJECTED"
