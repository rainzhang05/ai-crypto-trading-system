"""Bootstrap full-history backfill orchestration for Phase 6."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from execution.decision_engine import stable_hash
from execution.phase6.common import Phase6Database, deterministic_uuid
from execution.phase6.provider_contract import HistoricalProvider, OhlcvBar
from execution.phase6.trade_archive import archive_trade_ticks, persist_trade_chunk_manifest


@dataclass(frozen=True)
class BackfillResult:
    """Summary of one backfill cycle."""

    ingestion_cycle_id: str
    bars_written: int
    trades_archived: int
    symbols_completed: int
    completed: bool



def _build_ingestion_cycle_id(*tokens: object) -> str:
    return str(deterministic_uuid("phase6_ingestion_cycle", *tokens))


def _persist_cycle(
    db: Phase6Database,
    *,
    cycle_id: str,
    cycle_kind: str,
    started_at_utc: datetime,
    status: str,
    completed_at_utc: datetime | None,
    details_hash: str,
) -> None:
    db.execute(
        """
        INSERT INTO ingestion_cycle (
            ingestion_cycle_id, cycle_kind, started_at_utc, completed_at_utc,
            status, details_hash, row_hash
        ) VALUES (
            :ingestion_cycle_id, :cycle_kind, :started_at_utc, :completed_at_utc,
            :status, :details_hash, :row_hash
        )
        ON CONFLICT (ingestion_cycle_id) DO NOTHING
        """,
        {
            "ingestion_cycle_id": cycle_id,
            "cycle_kind": cycle_kind,
            "started_at_utc": started_at_utc,
            "completed_at_utc": completed_at_utc,
            "status": status,
            "details_hash": details_hash,
            "row_hash": stable_hash(("ingestion_cycle", cycle_id, status, details_hash)),
        },
    )


def _persist_ohlcv_rows(
    db: Phase6Database,
    *,
    ingest_run_id: str,
    asset_id: int,
    bars: Sequence[OhlcvBar],
) -> int:
    written = 0
    for bar in bars:
        row_hash = stable_hash(
            (
                "market_ohlcv_hourly",
                asset_id,
                bar.hour_ts_utc.isoformat(),
                bar.source_venue,
                str(bar.open_price),
                str(bar.high_price),
                str(bar.low_price),
                str(bar.close_price),
                str(bar.volume_base),
                str(bar.volume_quote),
                bar.trade_count,
            )
        )
        db.execute(
            """
            INSERT INTO market_ohlcv_hourly (
                asset_id, hour_ts_utc,
                open_price, high_price, low_price, close_price,
                volume_base, volume_quote, trade_count,
                source_venue, ingest_run_id, row_hash
            ) VALUES (
                :asset_id, :hour_ts_utc,
                :open_price, :high_price, :low_price, :close_price,
                :volume_base, :volume_quote, :trade_count,
                :source_venue, :ingest_run_id, :row_hash
            )
            ON CONFLICT (asset_id, hour_ts_utc, source_venue) DO NOTHING
            """,
            {
                "asset_id": asset_id,
                "hour_ts_utc": bar.hour_ts_utc,
                "open_price": bar.open_price,
                "high_price": bar.high_price,
                "low_price": bar.low_price,
                "close_price": bar.close_price,
                "volume_base": bar.volume_base,
                "volume_quote": bar.volume_quote,
                "trade_count": bar.trade_count,
                "source_venue": bar.source_venue,
                "ingest_run_id": ingest_run_id,
                "row_hash": row_hash,
            },
        )
        written += 1
    return written


def run_bootstrap_backfill(
    *,
    db: Phase6Database,
    provider: HistoricalProvider,
    universe_symbols: Sequence[str],
    asset_id_by_symbol: dict[str, int],
    local_cache_dir: str,
    start_ts_utc: datetime,
    end_ts_utc: datetime,
) -> BackfillResult:
    """Backfill full available history for all universe symbols."""
    if end_ts_utc <= start_ts_utc:
        raise RuntimeError("Bootstrap window must satisfy end_ts_utc > start_ts_utc")

    cycle_started = datetime.now(tz=timezone.utc)
    cycle_id = _build_ingestion_cycle_id("bootstrap", cycle_started.isoformat(), len(universe_symbols))

    _persist_cycle(
        db,
        cycle_id=cycle_id,
        cycle_kind="BOOTSTRAP",
        started_at_utc=cycle_started,
        status="RUNNING",
        completed_at_utc=None,
        details_hash=stable_hash(("bootstrap", start_ts_utc.isoformat(), end_ts_utc.isoformat())),
    )

    bars_written = 0
    trades_archived = 0
    completed_symbols = 0

    for symbol in universe_symbols:
        asset_id = asset_id_by_symbol[symbol]

        bars = provider.fetch_ohlcv(symbol, start_ts_utc, end_ts_utc, "1HRS")
        bars_written += _persist_ohlcv_rows(db, ingest_run_id=cycle_id, asset_id=asset_id, bars=bars)

        cursor: str | None = None
        step_start = start_ts_utc
        symbol_trade_count = 0
        while step_start < end_ts_utc:
            step_end = min(step_start + timedelta(days=7), end_ts_utc)
            trades, cursor = provider.fetch_trades(symbol, step_start, step_end, cursor)
            chunks = archive_trade_ticks(
                base_dir=Path(local_cache_dir),
                symbol=symbol,
                source="COINAPI",
                trades=trades,
            )
            persist_trade_chunk_manifest(
                db,
                ingestion_cycle_id=cycle_id,
                source="COINAPI",
                symbol=symbol,
                chunks=chunks,
            )
            symbol_trade_count += len(trades)
            step_start = step_end
            if cursor is None:
                continue

        trades_archived += symbol_trade_count

        watermark_hash = stable_hash(("bootstrap_watermark", symbol, end_ts_utc.isoformat(), symbol_trade_count))
        db.execute(
            """
            INSERT INTO ingestion_watermark_history (
                ingestion_cycle_id, source_name, symbol,
                watermark_kind, watermark_ts_utc, watermark_cursor,
                records_ingested, row_hash
            ) VALUES (
                :ingestion_cycle_id, :source_name, :symbol,
                :watermark_kind, :watermark_ts_utc, :watermark_cursor,
                :records_ingested, :row_hash
            )
            """,
            {
                "ingestion_cycle_id": cycle_id,
                "source_name": "COINAPI",
                "symbol": symbol,
                "watermark_kind": "BOOTSTRAP_END",
                "watermark_ts_utc": end_ts_utc,
                "watermark_cursor": cursor,
                "records_ingested": symbol_trade_count,
                "row_hash": watermark_hash,
            },
        )
        completed_symbols += 1

    _persist_cycle(
        db,
        cycle_id=cycle_id,
        cycle_kind="BOOTSTRAP",
        started_at_utc=cycle_started,
        status="COMPLETED",
        completed_at_utc=datetime.now(tz=timezone.utc),
        details_hash=stable_hash(("bootstrap_complete", bars_written, trades_archived, completed_symbols)),
    )

    return BackfillResult(
        ingestion_cycle_id=cycle_id,
        bars_written=bars_written,
        trades_archived=trades_archived,
        symbols_completed=completed_symbols,
        completed=completed_symbols == len(universe_symbols),
    )
