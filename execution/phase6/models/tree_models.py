"""Tree-model specialist training for Phase 6."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class TreeModelArtifact:
    """Trained tree-model artifact metadata."""

    symbol: str
    family: str
    artifact_path: Path
    train_rows: int
    metric_mse: float


_REQUIRED_TREE_LIBS: tuple[str, ...] = ("sklearn", "xgboost", "lightgbm")



def _assert_tree_dependencies() -> None:
    for name in _REQUIRED_TREE_LIBS:
        try:
            __import__(name)
        except ImportError as exc:
            raise RuntimeError(f"Missing required tree-model dependency: {name}") from exc



def train_tree_specialists(
    *,
    labeled_frame,
    symbols: Sequence[str],
    output_dir: Path,
    seed: int,
) -> tuple[TreeModelArtifact, ...]:
    """Train deterministic tree specialists for each symbol."""
    _assert_tree_dependencies()
    try:
        import numpy as np
        from joblib import dump
        from sklearn.ensemble import RandomForestRegressor
    except ImportError as exc:
        raise RuntimeError("Missing required dependency for tree specialist training") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[TreeModelArtifact] = []

    for symbol in sorted(symbols):
        symbol_frame = labeled_frame[labeled_frame["symbol"] == symbol]
        if symbol_frame.empty:
            continue
        x = symbol_frame[["roll_vol_32", "roll_liq_32", "order_flow_32"]].to_numpy(dtype=float)
        y = symbol_frame["label_ret_H1"].to_numpy(dtype=float)

        model = RandomForestRegressor(n_estimators=64, max_depth=6, random_state=seed)
        model.fit(x, y)
        pred = model.predict(x)
        mse = float(np.mean((pred - y) ** 2))

        artifact_path = output_dir / f"{symbol.lower()}_random_forest.joblib"
        dump(model, artifact_path)
        artifacts.append(
            TreeModelArtifact(
                symbol=symbol,
                family="RANDOM_FOREST",
                artifact_path=artifact_path,
                train_rows=int(len(symbol_frame)),
                metric_mse=mse,
            )
        )

    if not artifacts:
        raise RuntimeError("No tree specialists trained; labeled frame has no universe rows")

    return tuple(artifacts)
