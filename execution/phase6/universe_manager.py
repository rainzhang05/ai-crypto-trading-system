"""Universe governance and persistence for Phase 6 training symbols."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

from execution.decision_engine import stable_hash
from execution.phase6.common import Phase6Database
from execution.phase6.provider_contract import KrakenPairSnapshot, UniverseSymbolMeta


UNIVERSE_V1_SYMBOLS: tuple[str, ...] = (
    "BTC", "ETH", "BNB", "XRP", "SOL", "TRX", "ADA", "BCH", "XMR", "LINK",
    "XLM", "HBAR", "LTC", "AVAX", "ZEC", "SUI", "SHIB", "TON", "DOT", "UNI",
    "AAVE", "TAO", "NEAR", "ETC", "ICP", "POL", "KAS", "ALGO", "FIL", "APT",
)


@dataclass(frozen=True)
class UniverseRow:
    """Resolved universe row with tradability/parity metadata."""

    symbol: str
    market_cap_rank: int
    market_cap_usd: Decimal
    is_kraken_tradable: bool
    kraken_pair: str | None



def resolve_universe_rows(
    ranking_rows: Sequence[UniverseSymbolMeta],
    kraken_rows: Sequence[KrakenPairSnapshot],
) -> tuple[UniverseRow, ...]:
    """Build fixed V1 rows with Kraken tradability flags."""
    ranking_map: dict[str, UniverseSymbolMeta] = {row.symbol.upper(): row for row in ranking_rows}
    kraken_map: dict[str, KrakenPairSnapshot] = {}
    for row in kraken_rows:
        symbol = row.symbol.upper()
        current = kraken_map.get(symbol)
        if current is None or (row.is_tradable and not current.is_tradable):
            kraken_map[symbol] = row

    rows: list[UniverseRow] = []
    for idx, symbol in enumerate(UNIVERSE_V1_SYMBOLS, start=1):
        ranking = ranking_map.get(symbol)
        kraken = kraken_map.get(symbol)
        rows.append(
            UniverseRow(
                symbol=symbol,
                market_cap_rank=ranking.market_cap_rank if ranking is not None else idx,
                market_cap_usd=ranking.market_cap_usd if ranking is not None else Decimal("0"),
                is_kraken_tradable=bool(kraken and kraken.is_tradable),
                kraken_pair=kraken.kraken_pair if kraken is not None else None,
            )
        )
    return tuple(rows)


def universe_hash(rows: Iterable[UniverseRow]) -> str:
    """Compute deterministic universe hash."""
    tokens: list[object] = ["phase6_universe_v1"]
    for row in sorted(rows, key=lambda item: item.symbol):
        tokens.extend(
            (
                row.symbol,
                row.market_cap_rank,
                str(row.market_cap_usd),
                int(row.is_kraken_tradable),
                row.kraken_pair or "",
            )
        )
    return stable_hash(tokens)


def persist_universe_version(
    db: Phase6Database,
    *,
    version_code: str,
    generated_at_utc: datetime,
    rows: Sequence[UniverseRow],
    source_policy: str,
) -> str:
    """Persist universe version and symbol rows append-only."""
    u_hash = universe_hash(rows)
    row_hash = stable_hash(("training_universe_version", version_code, u_hash, source_policy))
    db.execute(
        """
        INSERT INTO training_universe_version (
            universe_version_code, generated_at_utc, universe_hash,
            source_policy, symbol_count, row_hash
        ) VALUES (
            :version_code, :generated_at_utc, :universe_hash,
            :source_policy, :symbol_count, :row_hash
        )
        ON CONFLICT (universe_version_code) DO NOTHING
        """,
        {
            "version_code": version_code,
            "generated_at_utc": generated_at_utc,
            "universe_hash": u_hash,
            "source_policy": source_policy,
            "symbol_count": len(rows),
            "row_hash": row_hash,
        },
    )

    for row in rows:
        symbol_row_hash = stable_hash(
            (
                "training_universe_symbol",
                version_code,
                row.symbol,
                row.market_cap_rank,
                str(row.market_cap_usd),
                int(row.is_kraken_tradable),
                row.kraken_pair or "",
            )
        )
        db.execute(
            """
            INSERT INTO training_universe_symbol (
                universe_version_code, symbol, market_cap_rank, market_cap_usd,
                is_kraken_tradable, kraken_pair, row_hash
            ) VALUES (
                :universe_version_code, :symbol, :market_cap_rank, :market_cap_usd,
                :is_kraken_tradable, :kraken_pair, :row_hash
            )
            ON CONFLICT (universe_version_code, symbol) DO NOTHING
            """,
            {
                "universe_version_code": version_code,
                "symbol": row.symbol,
                "market_cap_rank": row.market_cap_rank,
                "market_cap_usd": row.market_cap_usd,
                "is_kraken_tradable": row.is_kraken_tradable,
                "kraken_pair": row.kraken_pair,
                "row_hash": symbol_row_hash,
            },
        )

    return u_hash


def load_universe_symbols(db: Phase6Database, version_code: str) -> tuple[str, ...]:
    """Load persisted universe symbols for version."""
    rows = db.fetch_all(
        """
        SELECT symbol
        FROM training_universe_symbol
        WHERE universe_version_code = :universe_version_code
        ORDER BY market_cap_rank ASC, symbol ASC
        """,
        {"universe_version_code": version_code},
    )
    return tuple(str(row["symbol"]) for row in rows)
