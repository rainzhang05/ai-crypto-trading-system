"""Hindcast/forecast quality metric persistence for Phase 6."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from execution.decision_engine import stable_hash
from execution.phase6.common import Phase6Database


@dataclass(frozen=True)
class ForecastMetrics:
    """Deterministic rolling forecast metrics."""

    directional_accuracy: Decimal
    brier_score: Decimal
    ece: Decimal



def evaluate_forecast_metrics(frame: object, prob_col: str, target_col: str) -> ForecastMetrics:
    """Compute deterministic quality metrics from prediction frame."""
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("numpy is required for forecast metric evaluation") from exc

    if frame.empty:
        raise RuntimeError("Forecast metric frame is empty")

    prob = frame[prob_col].astype(float).to_numpy()
    target = frame[target_col].astype(float).to_numpy()

    pred = (prob >= 0.5).astype(float)
    directional_accuracy = Decimal(str(float(np.mean(pred == target))))
    brier = Decimal(str(float(np.mean((prob - target) ** 2))))

    bins = np.linspace(0.0, 1.0, 11)
    bin_idx = np.digitize(prob, bins, right=True)
    ece_value = 0.0
    for idx in range(0, len(bins) + 1):
        mask = bin_idx == idx
        if not np.any(mask):
            continue
        conf = float(np.mean(prob[mask]))
        acc = float(np.mean(target[mask]))
        ece_value += abs(conf - acc) * float(np.mean(mask))

    return ForecastMetrics(
        directional_accuracy=directional_accuracy,
        brier_score=brier,
        ece=Decimal(str(ece_value)),
    )


def persist_hindcast_forecast_metrics(
    db: Phase6Database,
    *,
    training_cycle_id: str,
    symbol: str,
    horizon: str,
    metric_kind: str,
    metrics: ForecastMetrics,
) -> None:
    """Persist one hindcast/forecast metric row."""
    measured_at = datetime.now(tz=timezone.utc)
    row_hash = stable_hash(
        (
            "hindcast_forecast_metric",
            training_cycle_id,
            symbol,
            horizon,
            metric_kind,
            str(metrics.directional_accuracy),
            str(metrics.brier_score),
            str(metrics.ece),
        )
    )

    db.execute(
        """
        INSERT INTO hindcast_forecast_metric (
            training_cycle_id, symbol, horizon,
            metric_kind, directional_accuracy, brier_score,
            ece, measured_at_utc, row_hash
        ) VALUES (
            :training_cycle_id, :symbol, :horizon,
            :metric_kind, :directional_accuracy, :brier_score,
            :ece, :measured_at_utc, :row_hash
        )
        """,
        {
            "training_cycle_id": training_cycle_id,
            "symbol": symbol,
            "horizon": horizon,
            "metric_kind": metric_kind,
            "directional_accuracy": metrics.directional_accuracy,
            "brier_score": metrics.brier_score,
            "ece": metrics.ece,
            "measured_at_utc": measured_at,
            "row_hash": row_hash,
        },
    )
