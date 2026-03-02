"""Deterministic exchange adapter contracts for Phase 4 order lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from execution.deterministic_context import ExecutionContext


@dataclass(frozen=True)
class OrderAttemptRequest:
    """Deterministic order-attempt input payload."""

    asset_id: int
    side: str
    requested_qty: Decimal
    attempt_ts_utc: datetime


@dataclass(frozen=True)
class FillAttemptResult:
    """Deterministic exchange fill-attempt output payload."""

    filled_qty: Decimal
    reference_price: Decimal | None
    fill_price: Decimal | None
    liquidity_flag: str
    price_source: str


class ExchangeAdapter(Protocol):
    """Protocol for deterministic execution adapter implementations."""

    def simulate_attempt(
        self,
        context: "ExecutionContext",
        request: OrderAttemptRequest,
    ) -> FillAttemptResult:
        """Simulate one deterministic order attempt and return fill result."""
