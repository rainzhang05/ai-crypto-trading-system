"""Provider protocol and normalized market data types for Phase 6 ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Protocol, Sequence


@dataclass(frozen=True)
class OhlcvBar:
    """Normalized OHLCV bar payload."""

    symbol: str
    source_venue: str
    hour_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume_base: Decimal
    volume_quote: Decimal
    trade_count: int


@dataclass(frozen=True)
class TradeTick:
    """Normalized trade tick payload."""

    symbol: str
    source_venue: str
    trade_ts_utc: datetime
    exchange_trade_id: str
    price: Decimal
    size: Decimal
    side: str


@dataclass(frozen=True)
class UniverseSymbolMeta:
    """Universe ranking metadata."""

    symbol: str
    market_cap_rank: int
    market_cap_usd: Decimal


@dataclass(frozen=True)
class KrakenPairSnapshot:
    """Kraken pair metadata + latest ohlc continuity surface."""

    symbol: str
    kraken_pair: str
    is_tradable: bool
    last_hour_ts_utc: Optional[datetime]


class HistoricalProvider(Protocol):
    """Canonical provider interface used by Phase 6 automation."""

    def fetch_ohlcv(self, symbol: str, start_ts_utc: datetime, end_ts_utc: datetime, granularity: str) -> Sequence[OhlcvBar]:
        """Fetch normalized bars for symbol in [start, end)."""

    def fetch_trades(self, symbol: str, start_ts_utc: datetime, end_ts_utc: datetime, cursor: str | None) -> tuple[Sequence[TradeTick], str | None]:
        """Fetch normalized trades with pagination cursor."""

    def fetch_universe_metadata(self) -> Sequence[UniverseSymbolMeta]:
        """Fetch universe ranking metadata."""

    def fetch_kraken_pairs_and_ohlc(self) -> Sequence[KrakenPairSnapshot]:
        """Fetch Kraken tradability + continuity surfaces."""
