"""Drift detection and persistence for autonomous retraining triggers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from execution.decision_engine import stable_hash
from execution.phase6.common import Phase6Database, deterministic_uuid


@dataclass(frozen=True)
class DriftThresholds:
    """Configured drift thresholds."""

    accuracy_drop_pp: Decimal
    ece_delta: Decimal
    psi_threshold: Decimal


@dataclass(frozen=True)
class DriftObservation:
    """Observed drift metrics compared to baseline."""

    symbol: str
    horizon: str
    accuracy_drop_pp: Decimal
    ece_delta: Decimal
    psi_value: Decimal



def drift_triggered(observation: DriftObservation, thresholds: DriftThresholds) -> bool:
    """Return True when any configured drift condition is violated."""
    return (
        observation.accuracy_drop_pp >= thresholds.accuracy_drop_pp
        or observation.ece_delta >= thresholds.ece_delta
        or observation.psi_value >= thresholds.psi_threshold
    )


def persist_drift_event(
    db: Phase6Database,
    *,
    training_cycle_ref: str,
    observation: DriftObservation,
    thresholds: DriftThresholds,
) -> bool:
    """Persist deterministic drift event if triggered."""
    triggered = drift_triggered(observation, thresholds)
    if not triggered:
        return False

    event_id = str(
        deterministic_uuid(
            "phase6_drift_event",
            training_cycle_ref,
            observation.symbol,
            observation.horizon,
            str(observation.accuracy_drop_pp),
            str(observation.ece_delta),
            str(observation.psi_value),
        )
    )
    row_hash = stable_hash(("drift_event", event_id, training_cycle_ref, observation.symbol, observation.horizon))
    db.execute(
        """
        INSERT INTO drift_event (
            drift_event_id, training_cycle_ref, symbol,
            horizon, accuracy_drop_pp, ece_delta,
            psi_value, triggered_at_utc, threshold_hash, row_hash
        ) VALUES (
            :drift_event_id, :training_cycle_ref, :symbol,
            :horizon, :accuracy_drop_pp, :ece_delta,
            :psi_value, :triggered_at_utc, :threshold_hash, :row_hash
        )
        ON CONFLICT (drift_event_id) DO NOTHING
        """,
        {
            "drift_event_id": event_id,
            "training_cycle_ref": training_cycle_ref,
            "symbol": observation.symbol,
            "horizon": observation.horizon,
            "accuracy_drop_pp": observation.accuracy_drop_pp,
            "ece_delta": observation.ece_delta,
            "psi_value": observation.psi_value,
            "triggered_at_utc": datetime.now(tz=timezone.utc),
            "threshold_hash": stable_hash(
                (
                    "drift_thresholds",
                    str(thresholds.accuracy_drop_pp),
                    str(thresholds.ece_delta),
                    str(thresholds.psi_threshold),
                )
            ),
            "row_hash": row_hash,
        },
    )
    return True
