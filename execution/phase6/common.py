"""Shared deterministic helpers for Phase 6 data/training orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, Sequence
from uuid import UUID, uuid5, NAMESPACE_URL

from execution.decision_engine import stable_hash


class Phase6Database(Protocol):
    """Minimal DB protocol used by Phase 6 modules."""

    def fetch_one(self, sql: str, params: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        """Fetch one row."""

    def fetch_all(self, sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        """Fetch rows."""

    def execute(self, sql: str, params: Mapping[str, Any]) -> None:
        """Execute mutation statement."""


@dataclass(frozen=True)
class Phase6Clock:
    """Injectable UTC clock for deterministic testing."""

    def now_utc(self) -> datetime:
        """Return current UTC timestamp."""
        return datetime.now(tz=timezone.utc)


def ensure_dir(path: Path) -> None:
    """Create directory tree if missing."""
    path.mkdir(parents=True, exist_ok=True)


def deterministic_uuid(namespace: str, *tokens: object) -> UUID:
    """Build UUIDv5 from canonical hash tokens."""
    token_hash = stable_hash((namespace, *tokens))
    return uuid5(NAMESPACE_URL, f"phase6::{namespace}::{token_hash}")


def utc_iso(ts: datetime) -> str:
    """Normalize timestamp to UTC RFC3339 string."""
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def decimal_to_str(value: Decimal) -> str:
    """Canonical decimal serialization."""
    return format(value.normalize(), "f") if value != 0 else "0"
