"""Leakage-safe meta-ensemble training for Phase 6."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MetaEnsembleArtifact:
    """Trained meta-learner artifact metadata."""

    artifact_path: Path
    train_rows: int
    metric_mse: float



def train_meta_ensemble(
    *,
    oof_frame,
    output_dir: Path,
    seed: int,
) -> MetaEnsembleArtifact:
    """Train deterministic meta-learner on out-of-fold predictions."""
    try:
        import numpy as np
        from joblib import dump
        from sklearn.linear_model import Ridge
    except ImportError as exc:
        raise RuntimeError("Missing required dependency for meta ensemble: scikit-learn/joblib") from exc

    output_dir.mkdir(parents=True, exist_ok=True)

    required_cols = ["pred_tree", "pred_deep", "pred_regime", "target"]
    for col in required_cols:
        if col not in oof_frame.columns:
            raise RuntimeError(f"OOF frame is missing required column: {col}")

    x = oof_frame[["pred_tree", "pred_deep", "pred_regime"]].to_numpy(dtype=float)
    y = oof_frame["target"].to_numpy(dtype=float)
    if len(x) == 0:
        raise RuntimeError("No OOF rows available for meta ensemble")

    model = Ridge(alpha=1.0, random_state=seed)
    model.fit(x, y)
    pred = model.predict(x)
    mse = float(np.mean((pred - y) ** 2))

    artifact_path = output_dir / "meta_ensemble.joblib"
    dump(model, artifact_path)
    return MetaEnsembleArtifact(artifact_path=artifact_path, train_rows=int(len(x)), metric_mse=mse)
