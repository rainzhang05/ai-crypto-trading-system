from __future__ import annotations

from datetime import datetime, timezone
import json
from urllib.error import URLError

import pytest

from execution.phase6 import coinapi_provider, kraken_public_provider
from execution.phase6.coinapi_provider import CoinApiProvider
from execution.phase6.kraken_public_provider import KrakenPublicProvider



def test_coinapi_fetch_ohlcv_and_trades() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def requester(path: str, params: dict[str, object]):
        calls.append((path, params))
        if path.startswith("/v1/ohlcv"):
            return [
                {
                    "time_period_start": "2026-01-01T00:00:00Z",
                    "price_open": "1.0",
                    "price_high": "2.0",
                    "price_low": "0.5",
                    "price_close": "1.5",
                    "volume_traded": "10",
                    "volume_traded_quote": "15",
                    "trades_count": 5,
                }
            ]
        if path.startswith("/v1/trades"):
            return {
                "data": [
                    {
                        "time_exchange": "2026-01-01T00:01:00Z",
                        "uuid": "abc",
                        "price": "1.5",
                        "size": "2",
                        "taker_side": "BUY",
                    }
                ],
                "next_cursor": "cursor-2",
            }
        return []

    provider = CoinApiProvider(
        api_key="k",
        base_url="https://example.test",
        request_budget_per_minute=10,
        requester=requester,
    )
    bars = provider.fetch_ohlcv("BTCUSD", datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc), "1HRS")
    assert len(bars) == 1
    trades, cursor = provider.fetch_trades("BTCUSD", datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc), None)
    assert len(trades) == 1
    assert cursor == "cursor-2"
    assert provider.call_count == 2
    assert calls


def test_coinapi_budget_guard() -> None:
    provider = CoinApiProvider(api_key="k", base_url="https://example.test", request_budget_per_minute=0, requester=lambda _p, _q: [])
    with pytest.raises(RuntimeError, match="request budget exceeded"):
        provider.fetch_universe_metadata()


def test_coinapi_budget_window_resets() -> None:
    provider = CoinApiProvider(api_key="k", base_url="https://example.test", request_budget_per_minute=1, requester=lambda _p, _q: [])
    provider.fetch_universe_metadata()
    with pytest.raises(RuntimeError, match="request budget exceeded"):
        provider.fetch_universe_metadata()

    provider._window_minute_utc = datetime(2000, 1, 1, tzinfo=timezone.utc)
    provider.fetch_universe_metadata()


def test_kraken_public_fetch_pairs() -> None:
    provider = KrakenPublicProvider(
        base_url="https://api.kraken.com",
        requester=lambda _path, _params: {
            "result": {
                "XBTUSD": {"status": "online"},
                "ETHUSD": {"status": "cancel_only"},
            }
        },
    )
    rows = provider.fetch_kraken_pairs_and_ohlc()
    assert len(rows) == 2
    btc = [row for row in rows if row.symbol == "BTC"][0]
    assert btc.is_tradable is True


def test_coinapi_fetch_universe_metadata_and_fetch_kraken_pairs_passthrough() -> None:
    provider = CoinApiProvider(
        api_key="k",
        base_url="https://example.test",
        request_budget_per_minute=10,
        requester=lambda _path, _params: [
            {"asset_id": "eth", "data_symbols_count": 2, "volume_1hrs_usd": "20"},
            {"asset_id": "btc", "data_symbols_count": 1, "volume_1hrs_usd": "30"},
            {"asset_id": "", "data_symbols_count": 0, "volume_1hrs_usd": "0"},
        ],
    )
    rows = provider.fetch_universe_metadata()
    assert [row.symbol for row in rows] == ["BTC", "ETH"]
    assert provider.fetch_kraken_pairs_and_ohlc() == ()


def test_coinapi_fetch_trades_with_cursor_param() -> None:
    seen_params: dict[str, object] = {}

    def _requester(_path: str, params: dict[str, object]) -> list[dict[str, object]]:
        seen_params.update(params)
        return [{"time_exchange": "2026-01-01T00:01:00Z", "trade_id": "1", "price": "1.1", "size": "2", "taker_side": "sell"}]

    provider = CoinApiProvider(api_key="k", base_url="https://example.test", request_budget_per_minute=10, requester=_requester)
    trades, cursor = provider.fetch_trades(
        "BTCUSD",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
        "cursor-1",
    )
    assert "cursor" in seen_params
    assert seen_params["cursor"] == "cursor-1"
    assert cursor is None
    assert trades[0].side == "SELL"


class _DummyResponse:
    def __init__(self, payload: object) -> None:
        self._bytes = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        return None

    def read(self) -> bytes:
        return self._bytes


def test_coinapi_request_json_urllib_success(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CoinApiProvider(api_key="k", base_url="https://example.test", request_budget_per_minute=10)
    monkeypatch.setattr(coinapi_provider, "urlopen", lambda *_a, **_k: _DummyResponse([{"asset_id": "BTC"}]))
    rows = provider.fetch_universe_metadata()
    assert len(rows) == 1
    assert rows[0].symbol == "BTC"


def test_coinapi_request_json_urllib_retry_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CoinApiProvider(api_key="k", base_url="https://example.test", request_budget_per_minute=10)
    monkeypatch.setattr(coinapi_provider, "urlopen", lambda *_a, **_k: (_ for _ in ()).throw(URLError("boom")))
    with pytest.raises(RuntimeError, match="failed after retries"):
        provider.fetch_universe_metadata()


def test_coinapi_request_json_without_exception_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CoinApiProvider(api_key="k", base_url="https://example.test", request_budget_per_minute=10)
    monkeypatch.setattr(coinapi_provider, "range", lambda _n: [], raising=False)
    with pytest.raises(RuntimeError, match="failed without an exception"):
        provider.fetch_universe_metadata()


def test_kraken_symbol_parse_fallback_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = KrakenPublicProvider(base_url="https://api.kraken.com")
    assert provider._symbol_from_pair("DOGEJPY") == "DOGEJPY"

    monkeypatch.setattr(kraken_public_provider, "urlopen", lambda *_a, **_k: (_ for _ in ()).throw(URLError("fail")))
    with pytest.raises(RuntimeError, match="failed after retries"):
        provider.fetch_kraken_pairs_and_ohlc()


def test_kraken_request_json_urllib_success(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = KrakenPublicProvider(base_url="https://api.kraken.com")
    monkeypatch.setattr(
        kraken_public_provider,
        "urlopen",
        lambda *_a, **_k: _DummyResponse({"result": {"ETHUSD": {"status": "online"}}}),
    )
    rows = provider.fetch_kraken_pairs_and_ohlc()
    assert rows[0].symbol == "ETH"


def test_kraken_request_json_without_exception_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = KrakenPublicProvider(base_url="https://api.kraken.com")
    monkeypatch.setattr(kraken_public_provider, "range", lambda _n: [], raising=False)
    with pytest.raises(RuntimeError, match="failed without an exception"):
        provider.fetch_kraken_pairs_and_ohlc()
