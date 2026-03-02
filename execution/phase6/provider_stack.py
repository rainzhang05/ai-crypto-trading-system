"""Composed provider stack for CoinAPI + Kraken public policy."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from execution.phase6.coinapi_provider import CoinApiProvider
from execution.phase6.kraken_public_provider import KrakenPublicProvider
from execution.phase6.provider_contract import HistoricalProvider, KrakenPairSnapshot, OhlcvBar, TradeTick, UniverseSymbolMeta


class Phase6ProviderStack(HistoricalProvider):
    """Composed provider implementing policy-allowed Phase 6 sources."""

    def __init__(self, *, coinapi: CoinApiProvider, kraken_public: KrakenPublicProvider) -> None:
        self._coinapi = coinapi
        self._kraken = kraken_public

    @property
    def call_count(self) -> int | None:
        """Expose CoinAPI call counter for daemon progress/budget logging."""
        value = getattr(self._coinapi, "call_count", None)
        if isinstance(value, int):
            return value
        return None

    def fetch_ohlcv(self, symbol: str, start_ts_utc: datetime, end_ts_utc: datetime, granularity: str) -> Sequence[OhlcvBar]:
        return self._coinapi.fetch_ohlcv(symbol, start_ts_utc, end_ts_utc, granularity)

    def fetch_trades(self, symbol: str, start_ts_utc: datetime, end_ts_utc: datetime, cursor: str | None) -> tuple[Sequence[TradeTick], str | None]:
        return self._coinapi.fetch_trades(symbol, start_ts_utc, end_ts_utc, cursor)

    def fetch_universe_metadata(self) -> Sequence[UniverseSymbolMeta]:
        return self._coinapi.fetch_universe_metadata()

    def fetch_kraken_pairs_and_ohlc(self) -> Sequence[KrakenPairSnapshot]:
        return self._kraken.fetch_kraken_pairs_and_ohlc()
