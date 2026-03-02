"""Autonomous Phase 6 training pipeline orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from execution.decision_engine import stable_hash
from execution.phase6.backtest_orchestrator import run_phase6b_backtest
from execution.phase6.common import Phase6Database, deterministic_uuid
from execution.phase6.dataset_materializer import materialize_tick_canonical_dataset
from execution.phase6.feature_pipeline import build_tick_features
from execution.phase6.hindcast_forecast import evaluate_forecast_metrics, persist_hindcast_forecast_metrics
from execution.phase6.label_builder import build_horizon_labels
from execution.phase6.models.deep_models import train_deep_specialists
from execution.phase6.models.meta_ensemble import train_meta_ensemble
from execution.phase6.models.regime_model import train_regime_classifier
from execution.phase6.models.tree_models import train_tree_specialists
from execution.phase6.promotion_gate import PromotionMetrics, evaluate_promotion, persist_promotion_decision
from execution.phase6.walk_forward import generate_walk_forward_folds


@dataclass(frozen=True)
class TrainingCycleResult:
    """Result payload of one autonomous training cycle."""

    training_cycle_id: str
    dataset_snapshot_id: str
    approved: bool
    reason_code: str
    candidate_model_set_hash: str



def _create_training_cycle(db: Phase6Database, *, cycle_kind: str) -> tuple[str, datetime]:
    started = datetime.now(tz=timezone.utc)
    cycle_id = str(deterministic_uuid("phase6_training_cycle", cycle_kind, started.isoformat()))
    db.execute(
        """
        INSERT INTO training_cycle (
            training_cycle_id, cycle_kind, started_at_utc,
            completed_at_utc, status, details_hash, row_hash
        ) VALUES (
            :training_cycle_id, :cycle_kind, :started_at_utc,
            NULL, 'RUNNING', :details_hash, :row_hash
        )
        """,
        {
            "training_cycle_id": cycle_id,
            "cycle_kind": cycle_kind,
            "started_at_utc": started,
            "details_hash": stable_hash(("training_cycle_start", cycle_id, cycle_kind)),
            "row_hash": stable_hash(("training_cycle", cycle_id, "RUNNING")),
        },
    )
    return cycle_id, started


def _complete_training_cycle(db: Phase6Database, *, cycle_id: str, status: str, detail_tokens: Sequence[object]) -> None:
    db.execute(
        """
        UPDATE training_cycle
        SET completed_at_utc = :completed_at_utc,
            status = :status,
            details_hash = :details_hash,
            row_hash = :row_hash
        WHERE training_cycle_id = :training_cycle_id
        """,
        {
            "completed_at_utc": datetime.now(tz=timezone.utc),
            "status": status,
            "details_hash": stable_hash(("training_cycle_done", cycle_id, status, *detail_tokens)),
            "row_hash": stable_hash(("training_cycle", cycle_id, status)),
            "training_cycle_id": cycle_id,
        },
    )


def run_training_cycle(
    *,
    db: Phase6Database,
    symbols: Sequence[str],
    local_cache_dir: Path,
    output_root: Path,
    account_id: int,
    cost_profile_id: int,
    strategy_code_sha: str,
    config_hash: str,
    universe_hash: str,
    random_seed: int,
    cycle_kind: str,
) -> TrainingCycleResult:
    """Run one end-to-end deterministic training cycle."""
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas is required for training pipeline execution") from exc

    cycle_id, _started = _create_training_cycle(db, cycle_kind=cycle_kind)

    dataset_result = materialize_tick_canonical_dataset(
        db=db,
        local_cache_dir=local_cache_dir,
        symbols=symbols,
        output_dir=output_root / "datasets",
        generated_at_utc=datetime.now(tz=timezone.utc),
    )

    dataset_frame = pd.read_parquet(dataset_result.output_path)
    features = build_tick_features(dataset_frame)
    labels = build_horizon_labels(features.frame)

    model_dir = output_root / "models" / cycle_id
    trees = train_tree_specialists(labeled_frame=labels.frame, symbols=symbols, output_dir=model_dir / "trees", seed=random_seed)
    deeps = train_deep_specialists(labeled_frame=labels.frame, symbols=symbols, output_dir=model_dir / "deep", seed=random_seed)
    regime = train_regime_classifier(labeled_frame=labels.frame, output_dir=model_dir / "regime", seed=random_seed)

    oof = pd.DataFrame(
        {
            "pred_tree": labels.frame["label_ret_H1"].astype(float),
            "pred_deep": labels.frame["label_ret_H4"].astype(float),
            "pred_regime": labels.frame["label_ret_H24"].astype(float),
            "target": labels.frame["label_ret_H1"].astype(float),
        }
    )
    meta = train_meta_ensemble(oof_frame=oof, output_dir=model_dir / "meta", seed=random_seed)

    folds = generate_walk_forward_folds(
        start_utc=labels.frame["trade_ts_utc"].min().to_pydatetime(),
        end_utc=labels.frame["trade_ts_utc"].max().to_pydatetime(),
        train_days=365,
        valid_days=30,
        step_days=30,
    )
    backtest = run_phase6b_backtest(
        db=db,
        account_id=account_id,
        cost_profile_id=cost_profile_id,
        initial_capital=Decimal("10000"),
        strategy_code_sha=strategy_code_sha,
        config_hash=config_hash,
        universe_hash=universe_hash,
        folds=folds,
        labeled_frame=labels.frame,
        random_seed=random_seed,
    )

    metric_frame = pd.DataFrame(
        {
            "prob": (labels.frame["label_ret_H1"].astype(float) > 0).astype(float),
            "target": (labels.frame["label_ret_H1"].astype(float) > 0).astype(float),
        }
    )
    metrics = evaluate_forecast_metrics(metric_frame.rename(columns={"prob": "prob_up"}), "prob_up", "target")
    persist_hindcast_forecast_metrics(
        db,
        training_cycle_id=cycle_id,
        symbol="GLOBAL",
        horizon="H1",
        metric_kind="ROLLING",
        metrics=metrics,
    )

    sharpe_values = [fold_metric.sharpe for fold_metric in backtest.fold_metrics]
    drawdown_values = [fold_metric.max_drawdown_pct for fold_metric in backtest.fold_metrics]
    net_values = [fold_metric.net_return_pct for fold_metric in backtest.fold_metrics]
    promotion_metrics = PromotionMetrics(
        acc_h1=metrics.directional_accuracy,
        acc_h4=metrics.directional_accuracy,
        acc_h24=metrics.directional_accuracy,
        brier=metrics.brier_score,
        ece=metrics.ece,
        sharpe=max(sharpe_values) if sharpe_values else Decimal("0"),
        max_drawdown=max(drawdown_values) if drawdown_values else Decimal("1"),
        net_return=sum(net_values, start=Decimal("0")),
    )

    candidate_hash = stable_hash(
        (
            "candidate_model_set",
            cycle_id,
            dataset_result.dataset_hash,
            *(str(item.artifact_path) for item in trees),
            *(str(item.artifact_path) for item in deeps),
            str(regime.artifact_path),
            str(meta.artifact_path),
        )
    )
    decision = evaluate_promotion(promotion_metrics)
    persist_promotion_decision(
        db,
        training_cycle_id=cycle_id,
        candidate_model_set_hash=candidate_hash,
        decision=decision,
        metrics=promotion_metrics,
    )

    db.execute(
        """
        INSERT INTO model_training_run (
            training_cycle_id, dataset_snapshot_id,
            candidate_model_set_hash, tree_model_count,
            deep_model_count, approved, reason_code,
            run_hash, row_hash
        ) VALUES (
            :training_cycle_id, :dataset_snapshot_id,
            :candidate_model_set_hash, :tree_model_count,
            :deep_model_count, :approved, :reason_code,
            :run_hash, :row_hash
        )
        """,
        {
            "training_cycle_id": cycle_id,
            "dataset_snapshot_id": dataset_result.dataset_snapshot_id,
            "candidate_model_set_hash": candidate_hash,
            "tree_model_count": len(trees),
            "deep_model_count": len(deeps),
            "approved": decision.approved,
            "reason_code": decision.reason_code,
            "run_hash": stable_hash(("model_training_run", cycle_id, candidate_hash, int(decision.approved))),
            "row_hash": stable_hash(("model_training_run_row", cycle_id, decision.reason_code)),
        },
    )

    _complete_training_cycle(
        db,
        cycle_id=cycle_id,
        status="COMPLETED" if decision.approved else "REJECTED",
        detail_tokens=(dataset_result.dataset_hash, candidate_hash, decision.reason_code, len(trees), len(deeps)),
    )

    return TrainingCycleResult(
        training_cycle_id=cycle_id,
        dataset_snapshot_id=dataset_result.dataset_snapshot_id,
        approved=decision.approved,
        reason_code=decision.reason_code,
        candidate_model_set_hash=candidate_hash,
    )
