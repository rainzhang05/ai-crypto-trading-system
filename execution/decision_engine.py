"""Deterministic decision engine primitives for runtime and replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from hashlib import sha256
import uuid
from typing import Any, Iterable

NUMERIC_18 = Decimal("0.000000000000000001")
NUMERIC_10 = Decimal("0.0000000001")


def normalize_decimal(value: Decimal, scale: Decimal = NUMERIC_18) -> Decimal:
    """Quantize decimals to deterministic precision."""
    return value.quantize(scale, rounding=ROUND_HALF_EVEN)


def normalize_timestamp(value: datetime) -> str:
    """Normalize timestamps to UTC RFC3339 without subsecond truncation."""
    utc_value = value.astimezone(timezone.utc)
    return utc_value.isoformat().replace("+00:00", "Z")


def normalize_token(value: Any) -> str:
    """Serialize primitive values deterministically for hashing."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, Decimal):
        return format(normalize_decimal(value), "f")
    if isinstance(value, datetime):
        return normalize_timestamp(value)
    return str(value)


def stable_hash(tokens: Iterable[Any]) -> str:
    """Compute a stable SHA256 hash over canonical token serialization."""
    preimage = "|".join(normalize_token(token) for token in tokens)
    return sha256(preimage.encode("utf-8")).hexdigest()


def stable_uuid(namespace: str, tokens: Iterable[Any]) -> uuid.UUID:
    """Generate a deterministic UUIDv5 from canonical tokens."""
    name = f"{namespace}|{stable_hash(tokens)}"
    return uuid.uuid5(uuid.NAMESPACE_URL, name)


@dataclass(frozen=True)
class DecisionResult:
    """Pure deterministic decision payload."""

    decision_hash: str
    action: str
    direction: str
    confidence: Decimal
    position_size_fraction: Decimal


def deterministic_decision(
    prediction_hash: str,
    regime_hash: str,
    capital_state_hash: str,
    risk_state_hash: str,
    cluster_state_hash: str,
) -> DecisionResult:
    """Pure deterministic decision function with no external side effects."""
    decision_hash = stable_hash(
        (
            "phase_1d_decision_v1",
            prediction_hash,
            regime_hash,
            capital_state_hash,
            risk_state_hash,
            cluster_state_hash,
        )
    )
    score = int(decision_hash[:16], 16)
    action_idx = score % 3
    if action_idx == 0:
        action = "ENTER"
        direction = "LONG"
    elif action_idx == 1:
        action = "HOLD"
        direction = "FLAT"
    else:
        action = "EXIT"
        direction = "FLAT"

    confidence = normalize_decimal(
        Decimal(score % 10_000) / Decimal(10_000),
        scale=NUMERIC_10,
    )

    # Runtime risk constraints cap base position size at 2%; keep this deterministic.
    raw_fraction = Decimal((score // 10_000) % 2_000) / Decimal(100_000)
    position_size_fraction = normalize_decimal(raw_fraction, scale=NUMERIC_10)
    if action != "ENTER":
        position_size_fraction = Decimal("0").quantize(NUMERIC_10)

    return DecisionResult(
        decision_hash=decision_hash,
        action=action,
        direction=direction,
        confidence=confidence,
        position_size_fraction=position_size_fraction,
    )
