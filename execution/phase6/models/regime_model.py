"""Global regime classifier training for Phase 6."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RegimeArtifact:
    """Trained regime classifier artifact metadata."""

    artifact_path: Path
    train_rows: int
    metric_accuracy: float



def train_regime_classifier(*, labeled_frame, output_dir: Path, seed: int) -> RegimeArtifact:
    """Train deterministic global regime classifier."""
    try:
        import numpy as np
        from joblib import dump
        from sklearn.linear_model import LogisticRegression
    except ImportError as exc:
        raise RuntimeError("Missing required dependency for regime classifier: scikit-learn/joblib") from exc

    output_dir.mkdir(parents=True, exist_ok=True)

    x = labeled_frame[["roll_vol_32", "roll_liq_32", "order_flow_32"]].to_numpy(dtype=float)
    y = (labeled_frame["label_ret_H24"].to_numpy(dtype=float) > 0).astype(int)
    if len(x) == 0:
        raise RuntimeError("No rows available for regime classifier")

    model = LogisticRegression(max_iter=400, random_state=seed)
    model.fit(x, y)
    pred = model.predict(x)
    accuracy = float(np.mean(pred == y))

    artifact_path = output_dir / "global_regime.joblib"
    dump(model, artifact_path)
    return RegimeArtifact(artifact_path=artifact_path, train_rows=int(len(x)), metric_accuracy=accuracy)
