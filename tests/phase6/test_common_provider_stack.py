from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from execution.phase6.common import Phase6Clock, decimal_to_str, deterministic_uuid, ensure_dir, utc_iso
from execution.phase6.provider_contract import KrakenPairSnapshot, OhlcvBar, TradeTick, UniverseSymbolMeta
from execution.phase6.provider_stack import Phase6ProviderStack


def test_common_helpers_cover_all_paths(tmp_path: Path) -> None:
    clock = Phase6Clock()
    now = clock.now_utc()
    assert now.tzinfo is not None

    target = tmp_path / "a" / "b"
    ensure_dir(target)
    assert target.exists()

    uuid_1 = deterministic_uuid("x", 1, "a")
    uuid_2 = deterministic_uuid("x", 1, "a")
    assert str(uuid_1) == str(uuid_2)

    ts = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    assert utc_iso(ts) == "2026-01-01T08:00:00Z"

    assert decimal_to_str(Decimal("0")) == "0"
    assert decimal_to_str(Decimal("1.2300")) == "1.23"


class _FakeCoinApi:
    def fetch_ohlcv(self, symbol, start_ts_utc, end_ts_utc, granularity):  # type: ignore[no-untyped-def]
        return (
            OhlcvBar(
                symbol=symbol,
                source_venue="COINAPI",
                hour_ts_utc=start_ts_utc,
                open_price=Decimal("1"),
                high_price=Decimal("2"),
                low_price=Decimal("0.5"),
                close_price=Decimal("1.5"),
                volume_base=Decimal("10"),
                volume_quote=Decimal("12"),
                trade_count=3,
            ),
        )

    def fetch_trades(self, symbol, start_ts_utc, end_ts_utc, cursor):  # type: ignore[no-untyped-def]
        return (
            (
                TradeTick(
                    symbol=symbol,
                    source_venue="COINAPI",
                    trade_ts_utc=start_ts_utc,
                    exchange_trade_id="t1",
                    price=Decimal("1"),
                    size=Decimal("1"),
                    side="BUY",
                ),
            ),
            cursor,
        )

    def fetch_universe_metadata(self):  # type: ignore[no-untyped-def]
        return (UniverseSymbolMeta(symbol="BTC", market_cap_rank=1, market_cap_usd=Decimal("100")),)


class _FakeKraken:
    def fetch_kraken_pairs_and_ohlc(self):  # type: ignore[no-untyped-def]
        return (
            KrakenPairSnapshot(
                symbol="BTC",
                kraken_pair="XBTUSD",
                is_tradable=True,
                last_hour_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        )


def test_provider_stack_delegates() -> None:
    stack = Phase6ProviderStack(coinapi=_FakeCoinApi(), kraken_public=_FakeKraken())
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)

    bars = stack.fetch_ohlcv("BTCUSD", start, end, "1HRS")
    trades, cursor = stack.fetch_trades("BTCUSD", start, end, None)
    universe = stack.fetch_universe_metadata()
    kraken = stack.fetch_kraken_pairs_and_ohlc()

    assert len(bars) == 1
    assert len(trades) == 1
    assert cursor is None
    assert universe[0].symbol == "BTC"
    assert kraken[0].kraken_pair == "XBTUSD"
