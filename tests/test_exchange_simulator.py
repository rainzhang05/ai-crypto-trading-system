"""Unit tests for deterministic exchange simulator behavior."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from execution.exchange_adapter import OrderAttemptRequest
from execution.exchange_simulator import DeterministicExchangeSimulator
from execution.replay_engine import _attempt_timestamps


@dataclass(frozen=True)
class _Snapshot:
    asset_id: int
    snapshot_ts_utc: datetime
    best_bid_price: Decimal
    best_ask_price: Decimal
    best_bid_size: Decimal
    best_ask_size: Decimal


@dataclass(frozen=True)
class _Candle:
    asset_id: int
    close_price: Decimal


class _Context:
    def __init__(self, snapshot: _Snapshot | None, candle: _Candle | None) -> None:
        self._snapshot = snapshot
        self._candle = candle

    def find_latest_order_book_snapshot(self, asset_id: int, as_of_ts_utc: datetime) -> _Snapshot | None:
        if self._snapshot is None:
            return None
        if self._snapshot.asset_id != asset_id:
            return None
        if self._snapshot.snapshot_ts_utc > as_of_ts_utc:
            return None
        return self._snapshot

    def find_ohlcv(self, asset_id: int) -> _Candle | None:
        if self._candle is None:
            return None
        if self._candle.asset_id != asset_id:
            return None
        return self._candle


def test_exchange_simulator_order_book_path_and_partial_fill() -> None:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    context = _Context(
        snapshot=_Snapshot(
            asset_id=1,
            snapshot_ts_utc=ts,
            best_bid_price=Decimal("99.000000000000000000"),
            best_ask_price=Decimal("100.000000000000000000"),
            best_bid_size=Decimal("3.000000000000000000"),
            best_ask_size=Decimal("2.000000000000000000"),
        ),
        candle=None,
    )
    simulator = DeterministicExchangeSimulator()

    buy = simulator.simulate_attempt(
        context,
        OrderAttemptRequest(
            asset_id=1,
            side="BUY",
            requested_qty=Decimal("5.000000000000000000"),
            attempt_ts_utc=ts,
        ),
    )
    assert buy.price_source == "ORDER_BOOK"
    assert buy.reference_price == Decimal("100.000000000000000000")
    assert buy.fill_price == Decimal("100.000000000000000000")
    assert buy.filled_qty == Decimal("2.000000000000000000")
    assert buy.liquidity_flag == "TAKER"

    sell = simulator.simulate_attempt(
        context,
        OrderAttemptRequest(
            asset_id=1,
            side="SELL",
            requested_qty=Decimal("1.000000000000000000"),
            attempt_ts_utc=ts,
        ),
    )
    assert sell.price_source == "ORDER_BOOK"
    assert sell.reference_price == Decimal("99.000000000000000000")
    assert sell.fill_price == Decimal("99.000000000000000000")
    assert sell.filled_qty == Decimal("1.000000000000000000")


def test_exchange_simulator_ohlcv_fallback_path() -> None:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    context = _Context(
        snapshot=None,
        candle=_Candle(asset_id=1, close_price=Decimal("98.000000000000000000")),
    )
    simulator = DeterministicExchangeSimulator()
    result = simulator.simulate_attempt(
        context,
        OrderAttemptRequest(
            asset_id=1,
            side="BUY",
            requested_qty=Decimal("4.000000000000000000"),
            attempt_ts_utc=ts,
        ),
    )
    assert result.price_source == "OHLCV_CLOSE"
    assert result.fill_price == Decimal("98.000000000000000000")
    assert result.filled_qty == Decimal("4.000000000000000000")
    assert result.liquidity_flag == "UNKNOWN"


def test_exchange_simulator_unavailable_price_path() -> None:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    context = _Context(snapshot=None, candle=None)
    simulator = DeterministicExchangeSimulator()
    result = simulator.simulate_attempt(
        context,
        OrderAttemptRequest(
            asset_id=1,
            side="BUY",
            requested_qty=Decimal("1.000000000000000000"),
            attempt_ts_utc=ts,
        ),
    )
    assert result.price_source == "UNAVAILABLE"
    assert result.reference_price is None
    assert result.fill_price is None
    assert result.filled_qty == Decimal("0.000000000000000000")


def test_deterministic_retry_backoff_schedule() -> None:
    origin = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert _attempt_timestamps(origin) == (
        datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 7, tzinfo=timezone.utc),
    )
