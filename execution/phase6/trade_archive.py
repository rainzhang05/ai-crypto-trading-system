"""Deterministic local raw-trade archive handling for Phase 6."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Sequence

from execution.decision_engine import stable_hash
from execution.phase6.common import ensure_dir, utc_iso, Phase6Database
from execution.phase6.provider_contract import TradeTick


@dataclass(frozen=True)
class RawTradeChunk:
    """Local archive chunk metadata."""

    symbol: str
    day_utc: str
    file_path: Path
    row_count: int
    min_trade_ts_utc: datetime
    max_trade_ts_utc: datetime
    file_sha256: str
    chunk_hash: str



def _trade_sort_key(trade: TradeTick) -> tuple[datetime, str, str, str]:
    return (
        trade.trade_ts_utc,
        trade.exchange_trade_id,
        str(trade.price),
        str(trade.size),
    )


def _compute_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_trade_ticks(
    *,
    base_dir: Path,
    symbol: str,
    source: str,
    trades: Sequence[TradeTick],
) -> tuple[RawTradeChunk, ...]:
    """Write deterministic parquet partitions for trade ticks."""
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas and pyarrow are required for trade archive writes") from exc

    if not trades:
        return tuple()

    grouped: dict[str, list[TradeTick]] = {}
    for trade in sorted(trades, key=_trade_sort_key):
        day = trade.trade_ts_utc.astimezone(timezone.utc).strftime("%Y-%m-%d")
        grouped.setdefault(day, []).append(trade)

    chunks: list[RawTradeChunk] = []
    for day, day_trades in sorted(grouped.items()):
        out_dir = base_dir / source.lower() / "trades" / symbol / f"date={day}"
        ensure_dir(out_dir)

        first_ts = day_trades[0].trade_ts_utc.astimezone(timezone.utc)
        last_ts = day_trades[-1].trade_ts_utc.astimezone(timezone.utc)
        chunk_hash = stable_hash(
            (
                "raw_trade_chunk",
                symbol,
                source,
                day,
                len(day_trades),
                utc_iso(first_ts),
                utc_iso(last_ts),
            )
        )
        file_name = f"chunk_{chunk_hash[:16]}.parquet"
        file_path = out_dir / file_name

        frame = pd.DataFrame(
            {
                "symbol": [trade.symbol for trade in day_trades],
                "source_venue": [trade.source_venue for trade in day_trades],
                "trade_ts_utc": [trade.trade_ts_utc.astimezone(timezone.utc) for trade in day_trades],
                "exchange_trade_id": [trade.exchange_trade_id for trade in day_trades],
                "price": [str(trade.price) for trade in day_trades],
                "size": [str(trade.size) for trade in day_trades],
                "side": [trade.side for trade in day_trades],
            }
        )
        frame.to_parquet(file_path, index=False)
        file_sha = _compute_sha256(file_path)

        chunks.append(
            RawTradeChunk(
                symbol=symbol,
                day_utc=day,
                file_path=file_path,
                row_count=len(day_trades),
                min_trade_ts_utc=first_ts,
                max_trade_ts_utc=last_ts,
                file_sha256=file_sha,
                chunk_hash=chunk_hash,
            )
        )

    return tuple(chunks)


def persist_trade_chunk_manifest(
    db: Phase6Database,
    *,
    ingestion_cycle_id: str,
    source: str,
    symbol: str,
    chunks: Iterable[RawTradeChunk],
) -> None:
    """Persist local archive chunk metadata lineage."""
    for chunk in chunks:
        row_hash = stable_hash(
            (
                "raw_trade_chunk_manifest",
                ingestion_cycle_id,
                source,
                symbol,
                chunk.day_utc,
                chunk.file_sha256,
                chunk.chunk_hash,
            )
        )
        db.execute(
            """
            INSERT INTO raw_trade_chunk_manifest (
                ingestion_cycle_id, source_name, symbol, day_utc,
                file_path, file_sha256, row_count,
                min_trade_ts_utc, max_trade_ts_utc,
                chunk_hash, row_hash
            ) VALUES (
                :ingestion_cycle_id, :source_name, :symbol, :day_utc,
                :file_path, :file_sha256, :row_count,
                :min_trade_ts_utc, :max_trade_ts_utc,
                :chunk_hash, :row_hash
            )
            ON CONFLICT (source_name, symbol, day_utc, file_sha256) DO NOTHING
            """,
            {
                "ingestion_cycle_id": ingestion_cycle_id,
                "source_name": source,
                "symbol": symbol,
                "day_utc": chunk.day_utc,
                "file_path": str(chunk.file_path),
                "file_sha256": chunk.file_sha256,
                "row_count": chunk.row_count,
                "min_trade_ts_utc": chunk.min_trade_ts_utc,
                "max_trade_ts_utc": chunk.max_trade_ts_utc,
                "chunk_hash": chunk.chunk_hash,
                "row_hash": row_hash,
            },
        )
