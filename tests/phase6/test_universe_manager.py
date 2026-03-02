from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from execution.phase6.provider_contract import KrakenPairSnapshot, UniverseSymbolMeta
from execution.phase6.universe_manager import (
    UNIVERSE_V1_SYMBOLS,
    load_universe_symbols,
    persist_universe_version,
    resolve_universe_rows,
    universe_hash,
)
from tests.phase6.utils import FakeDB



def test_resolve_universe_rows_and_hash() -> None:
    ranking = (
        UniverseSymbolMeta(symbol="BTC", market_cap_rank=1, market_cap_usd=Decimal("100")),
        UniverseSymbolMeta(symbol="ETH", market_cap_rank=2, market_cap_usd=Decimal("90")),
    )
    kraken = (
        KrakenPairSnapshot(symbol="BTC", kraken_pair="XBTUSD", is_tradable=True, last_hour_ts_utc=None),
        KrakenPairSnapshot(symbol="ETH", kraken_pair="ETHUSD", is_tradable=False, last_hour_ts_utc=None),
    )

    rows = resolve_universe_rows(ranking, kraken)
    assert len(rows) == len(UNIVERSE_V1_SYMBOLS)
    btc = [row for row in rows if row.symbol == "BTC"][0]
    assert btc.is_kraken_tradable is True
    assert universe_hash(rows)



def test_resolve_universe_rows_prefers_tradable_and_keeps_existing_tradable() -> None:
    rows = resolve_universe_rows(
        (),
        (
            KrakenPairSnapshot(symbol="BTC", kraken_pair="XBTUSD", is_tradable=True, last_hour_ts_utc=None),
            KrakenPairSnapshot(symbol="BTC", kraken_pair="XBTUSD.OLD", is_tradable=False, last_hour_ts_utc=None),
            KrakenPairSnapshot(symbol="ETH", kraken_pair="ETHUSD.OFF", is_tradable=False, last_hour_ts_utc=None),
            KrakenPairSnapshot(symbol="ETH", kraken_pair="ETHUSD", is_tradable=True, last_hour_ts_utc=None),
        ),
    )
    btc = [row for row in rows if row.symbol == "BTC"][0]
    eth = [row for row in rows if row.symbol == "ETH"][0]
    assert btc.kraken_pair == "XBTUSD"
    assert eth.kraken_pair == "ETHUSD"


def test_persist_and_load_universe_symbols() -> None:
    db = FakeDB()
    rows = resolve_universe_rows((), ())
    u_hash = persist_universe_version(
        db,
        version_code="UNIVERSE_V1_TOP30_NON_STABLE",
        generated_at_utc=datetime.now(tz=timezone.utc),
        rows=rows,
        source_policy="COINAPI+KRAKEN_PUBLIC",
    )
    assert u_hash
    assert len(db.executed) == 1 + len(rows)

    db.set_all(
        "FROM training_universe_symbol",
        [{"symbol": "BTC"}, {"symbol": "ETH"}],
    )
    loaded = load_universe_symbols(db, "UNIVERSE_V1_TOP30_NON_STABLE")
    assert loaded == ("BTC", "ETH")
