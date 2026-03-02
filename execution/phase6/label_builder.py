"""Deterministic label construction for governed horizons."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LabelFrame:
    """Horizon label frame for training."""

    frame: object
    label_hash: str


_HORIZON_STEPS: dict[str, int] = {"H1": 60, "H4": 240, "H24": 1440}



def build_horizon_labels(feature_frame: object) -> LabelFrame:
    """Build future-return labels with strict causal alignment."""
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas is required for label construction") from exc

    if feature_frame.empty:
        raise RuntimeError("Feature frame is empty")

    frame = feature_frame.sort_values(["symbol", "trade_ts_utc", "exchange_trade_id"]).copy()
    for horizon, step in _HORIZON_STEPS.items():
        future_col = f"future_price_{horizon}"
        label_col = f"label_ret_{horizon}"
        frame[future_col] = frame.groupby("symbol")["price"].shift(-step)
        frame[label_col] = (frame[future_col] - frame["price"]) / frame["price"]

    label_cols = [f"label_ret_{h}" for h in _HORIZON_STEPS]
    frame = frame.dropna(subset=label_cols)
    label_hash = str(
        abs(hash(tuple(frame[["symbol", "trade_ts_utc", *label_cols]].head(1024).itertuples(index=False, name=None))))
    )
    return LabelFrame(frame=frame, label_hash=label_hash)
