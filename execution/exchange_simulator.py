"""Deterministic simulated exchange adapter for Phase 4 order lifecycle."""

from __future__ import annotations

from decimal import Decimal

from execution.decision_engine import normalize_decimal
from execution.exchange_adapter import ExchangeAdapter, FillAttemptResult, OrderAttemptRequest


class DeterministicExchangeSimulator(ExchangeAdapter):
    """Deterministic order simulation using order book with OHLCV fallback."""

    def simulate_attempt(self, context, request: OrderAttemptRequest) -> FillAttemptResult:
        snapshot = context.find_latest_order_book_snapshot(request.asset_id, request.attempt_ts_utc)
        if snapshot is not None:
            if request.side == "BUY":
                reference_price = snapshot.best_ask_price
                available_qty = snapshot.best_ask_size
            else:
                reference_price = snapshot.best_bid_price
                available_qty = snapshot.best_bid_size

            normalized_available = normalize_decimal(max(Decimal("0"), available_qty))
            filled_qty = normalize_decimal(min(request.requested_qty, normalized_available))
            return FillAttemptResult(
                filled_qty=filled_qty,
                reference_price=reference_price,
                fill_price=reference_price,
                liquidity_flag="TAKER",
                price_source="ORDER_BOOK",
            )

        candle = context.find_ohlcv(request.asset_id)
        if candle is None:
            return FillAttemptResult(
                filled_qty=Decimal("0.000000000000000000"),
                reference_price=None,
                fill_price=None,
                liquidity_flag="UNKNOWN",
                price_source="UNAVAILABLE",
            )

        reference_price = candle.close_price
        filled_qty = normalize_decimal(request.requested_qty)
        return FillAttemptResult(
            filled_qty=filled_qty,
            reference_price=reference_price,
            fill_price=reference_price,
            liquidity_flag="UNKNOWN",
            price_source="OHLCV_CLOSE",
        )
