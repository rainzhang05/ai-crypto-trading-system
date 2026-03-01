"""Deterministic model activation gate enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class ActivationRecord:
    """Projection of model_activation_gate for deterministic checks."""

    activation_id: int
    model_version_id: int
    run_mode: str
    validation_window_end_utc: datetime
    status: str
    approval_hash: str


@dataclass(frozen=True)
class ActivationGateResult:
    """Activation gate evaluation result."""

    allowed: bool
    reason_code: str
    detail: str


def enforce_activation_gate(
    run_mode: str,
    hour_ts_utc: datetime,
    model_version_id: int,
    activation: Optional[ActivationRecord],
) -> ActivationGateResult:
    """Validate activation policy before runtime execution."""
    normalized_mode = run_mode.upper()

    if normalized_mode == "BACKTEST":
        if activation is not None:
            return ActivationGateResult(
                allowed=False,
                reason_code="BACKTEST_ACTIVATION_PRESENT",
                detail="BACKTEST rows must not bind to model_activation_gate.",
            )
        return ActivationGateResult(
            allowed=True,
            reason_code="OK",
            detail="Backtest mode validated without activation dependency.",
        )

    if activation is None:
        return ActivationGateResult(
            allowed=False,
            reason_code="MISSING_ACTIVATION",
            detail="Live/Paper prediction missing activation binding.",
        )

    if activation.model_version_id != model_version_id:
        return ActivationGateResult(
            allowed=False,
            reason_code="ACTIVATION_MODEL_MISMATCH",
            detail="Activation model_version_id mismatch.",
        )

    if activation.run_mode != normalized_mode:
        return ActivationGateResult(
            allowed=False,
            reason_code="ACTIVATION_MODE_MISMATCH",
            detail="Activation run_mode mismatch.",
        )

    if activation.status != "APPROVED":
        return ActivationGateResult(
            allowed=False,
            reason_code="ACTIVATION_NOT_APPROVED",
            detail="Activation record is not APPROVED.",
        )

    if activation.validation_window_end_utc > hour_ts_utc:
        return ActivationGateResult(
            allowed=False,
            reason_code="ACTIVATION_WINDOW_NOT_REACHED",
            detail="Validation window ends after execution hour.",
        )

    return ActivationGateResult(
        allowed=True,
        reason_code="OK",
        detail="Activation gate passed.",
    )
