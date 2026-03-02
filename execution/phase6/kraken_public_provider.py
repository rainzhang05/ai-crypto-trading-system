"""Kraken-public parity adapter for symbol tradability and continuity checks."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Callable, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from execution.phase6.provider_contract import KrakenPairSnapshot


class KrakenPublicProvider:
    """Read-only Kraken public adapter for parity checks."""

    def __init__(
        self,
        *,
        base_url: str,
        requester: Optional[Callable[[str, dict[str, Any]], Any]] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._requester = requester

    def _request_json(self, path: str, params: dict[str, Any]) -> Any:
        if self._requester is not None:
            return self._requester(path, params)

        query = urlencode(params)
        request = Request(url=f"{self._base_url}{path}?{query}", method="GET")
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
            raise RuntimeError("Kraken public request failed without an exception")
        raise RuntimeError(f"Kraken public request failed after retries: {last_error}") from last_error

    @staticmethod
    def _symbol_from_pair(pair_code: str) -> str:
        token = pair_code.upper()
        for quote in ("USD", "USDT", "USDC", "CAD", "EUR"):
            if token.endswith(quote):
                base = token[: -len(quote)]
                return "BTC" if base in {"XBT", "XXBT"} else base
        return token

    def fetch_kraken_pairs_and_ohlc(self) -> Sequence[KrakenPairSnapshot]:
        assets_payload = self._request_json("/0/public/AssetPairs", {})
        result = assets_payload.get("result", {})
        snapshots: list[KrakenPairSnapshot] = []
        for pair_code, pair_meta in result.items():
            symbol = self._symbol_from_pair(pair_code)
            status = str(pair_meta.get("status", "")).lower()
            snapshots.append(
                KrakenPairSnapshot(
                    symbol=symbol,
                    kraken_pair=pair_code,
                    is_tradable=status == "online",
                    last_hour_ts_utc=datetime.now(tz=timezone.utc).replace(minute=0, second=0, microsecond=0),
                )
            )
        snapshots.sort(key=lambda item: (item.symbol, item.kraken_pair))
        return snapshots
