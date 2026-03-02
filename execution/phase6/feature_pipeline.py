"""Deterministic feature engineering from tick-canonical datasets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureFrame:
    """Model-ready feature frame metadata."""

    frame: object
    feature_hash: str



def build_tick_features(dataset: object) -> FeatureFrame:
    """Build deterministic tick-level features."""
    try:
        import numpy as np
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("numpy and pandas are required for feature engineering") from exc

    if dataset.empty:
        raise RuntimeError("Dataset is empty")

    frame = dataset.copy()
    frame["price"] = frame["price"].astype(float)
    frame["size"] = frame["size"].astype(float)
    frame["trade_ts_utc"] = pd.to_datetime(frame["trade_ts_utc"], utc=True)

    frame = frame.sort_values(["symbol", "trade_ts_utc", "exchange_trade_id"])
    # Use transform to preserve index alignment while keeping strictly causal returns.
    frame["log_return"] = frame.groupby("symbol")["price"].transform(
        lambda s: np.log(s / s.shift(1)).replace([np.inf, -np.inf], 0.0).fillna(0.0)
    )
    frame["signed_size"] = frame.apply(
        lambda row: row["size"] if str(row.get("side", "")).upper() == "BUY" else -row["size"],
        axis=1,
    )
    frame["roll_vol_32"] = frame.groupby("symbol")["log_return"].transform(
        lambda s: s.rolling(32, min_periods=4).std().fillna(0.0)
    )
    frame["roll_liq_32"] = frame.groupby("symbol")["size"].transform(
        lambda s: s.rolling(32, min_periods=4).mean().fillna(0.0)
    )
    frame["order_flow_32"] = frame.groupby("symbol")["signed_size"].transform(
        lambda s: s.rolling(32, min_periods=4).sum().fillna(0.0)
    )

    feature_hash = str(
        abs(
            hash(
                tuple(
                    frame[
                        [
                            "symbol",
                            "trade_ts_utc",
                            "log_return",
                            "roll_vol_32",
                            "roll_liq_32",
                            "order_flow_32",
                        ]
                    ]
                    .head(2048)
                    .itertuples(index=False, name=None)
                )
            )
        )
    )
    return FeatureFrame(frame=frame, feature_hash=feature_hash)
