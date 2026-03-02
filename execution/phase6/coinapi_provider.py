"""CoinAPI-backed historical provider adapter for Phase 6."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from typing import Any, Callable, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from execution.phase6.provider_contract import OhlcvBar, TradeTick, UniverseSymbolMeta, KrakenPairSnapshot


class CoinApiProvider:
    """CoinAPI adapter with deterministic normalization and bounded retries."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        request_budget_per_minute: int,
        requester: Optional[Callable[[str, dict[str, Any]], Any]] = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._request_budget_per_minute = request_budget_per_minute
        self._requester = requester
        self._call_count = 0
        self._window_minute_utc: datetime | None = None
        self._window_call_count = 0

    @property
    def call_count(self) -> int:
        """Return provider request call count for lineage accounting."""
        return self._call_count

    def _guard_budget(self) -> None:
        now_minute = datetime.now(tz=timezone.utc).replace(second=0, microsecond=0)
        if self._window_minute_utc != now_minute:
            self._window_minute_utc = now_minute
            self._window_call_count = 0
        if self._window_call_count >= self._request_budget_per_minute:
            raise RuntimeError("CoinAPI request budget exceeded for current cycle")

    def _request_json(self, path: str, params: dict[str, Any]) -> Any:
        self._guard_budget()
        self._call_count += 1
        self._window_call_count += 1
        if self._requester is not None:
            return self._requester(path, params)

        query = urlencode(params)
        request = Request(
            url=f"{self._base_url}{path}?{query}",
            headers={"X-CoinAPI-Key": self._api_key},
            method="GET",
        )

        last_error: Exception | None = None
        for _ in range(3):
            try:
                with urlopen(request, timeout=20.0) as response:
                    payload = response.read().decode("utf-8")
                    return json.loads(payload)
            except (HTTPError, URLError, TimeoutError) as exc:
                last_error = exc
                continue

        if last_error is None:
            raise RuntimeError("CoinAPI request failed without an exception")
        raise RuntimeError(f"CoinAPI request failed after retries: {last_error}") from last_error

    @staticmethod
    def _parse_ts(value: str) -> datetime:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).astimezone(timezone.utc)

    def fetch_ohlcv(
        self,
        symbol: str,
        start_ts_utc: datetime,
        end_ts_utc: datetime,
        granularity: str,
    ) -> Sequence[OhlcvBar]:
        payload = self._request_json(
            f"/v1/ohlcv/{symbol}/history",
            {
                "period_id": granularity,
                "time_start": start_ts_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "time_end": end_ts_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "limit": 10000,
            },
        )
        bars: list[OhlcvBar] = []
        for row in payload:
            bars.append(
                OhlcvBar(
                    symbol=symbol,
                    source_venue="COINAPI",
                    hour_ts_utc=self._parse_ts(str(row["time_period_start"])).replace(minute=0, second=0, microsecond=0),
                    open_price=Decimal(str(row["price_open"])),
                    high_price=Decimal(str(row["price_high"])),
                    low_price=Decimal(str(row["price_low"])),
                    close_price=Decimal(str(row["price_close"])),
                    volume_base=Decimal(str(row.get("volume_traded", "0"))),
                    volume_quote=Decimal(str(row.get("volume_traded_quote", "0"))),
                    trade_count=int(row.get("trades_count", 0)),
                )
            )
        bars.sort(key=lambda item: item.hour_ts_utc)
        return bars

    def fetch_trades(
        self,
        symbol: str,
        start_ts_utc: datetime,
        end_ts_utc: datetime,
        cursor: str | None,
    ) -> tuple[Sequence[TradeTick], str | None]:
        params: dict[str, Any] = {
            "time_start": start_ts_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "time_end": end_ts_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "limit": 10000,
        }
        if cursor is not None:
            params["cursor"] = cursor

        payload = self._request_json(f"/v1/trades/{symbol}/history", params)
        if isinstance(payload, dict):
            rows = payload.get("data", ())
            next_cursor = payload.get("next_cursor")
        else:
            rows = payload
            next_cursor = None

        trades: list[TradeTick] = []
        for row in rows:
            trades.append(
                TradeTick(
                    symbol=symbol,
                    source_venue="COINAPI",
                    trade_ts_utc=self._parse_ts(str(row["time_exchange"])),
                    exchange_trade_id=str(row.get("uuid") or row.get("trade_id") or ""),
                    price=Decimal(str(row["price"])),
                    size=Decimal(str(row["size"])),
                    side=str(row.get("taker_side", "UNKNOWN")).upper(),
                )
            )
        trades.sort(key=lambda item: (item.trade_ts_utc, item.exchange_trade_id, item.price, item.size))
        return trades, next_cursor

    def fetch_universe_metadata(self) -> Sequence[UniverseSymbolMeta]:
        payload = self._request_json("/v1/assets", {"filter_asset_id": ""})
        symbols: list[UniverseSymbolMeta] = []
        for row in payload:
            asset = str(row.get("asset_id", "")).upper()
            rank = int(row.get("data_symbols_count", 0))
            cap = Decimal(str(row.get("volume_1hrs_usd", "0")))
            if asset:
                symbols.append(UniverseSymbolMeta(symbol=asset, market_cap_rank=rank, market_cap_usd=cap))
        symbols.sort(key=lambda item: (-item.market_cap_usd, item.symbol))
        return symbols

    def fetch_kraken_pairs_and_ohlc(self) -> Sequence[KrakenPairSnapshot]:
        # CoinAPI provider does not emit Kraken parity directly; returned empty and handled by dedicated adapter.
        return ()
