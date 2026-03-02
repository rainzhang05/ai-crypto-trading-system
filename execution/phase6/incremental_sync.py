"""Incremental ingestion cycle orchestration for Phase 6."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from execution.decision_engine import stable_hash
from execution.phase6.common import Phase6Database, deterministic_uuid
from execution.phase6.provider_contract import HistoricalProvider
from execution.phase6.trade_archive import archive_trade_ticks, persist_trade_chunk_manifest


@dataclass(frozen=True)
class IncrementalSyncResult:
    """Summary payload for incremental sync cycle."""

    ingestion_cycle_id: str
    symbols_synced: int
    symbols_throttled: int
    bars_written: int
    trades_archived: int
    ohlcv_api_calls: int
    trade_api_calls: int



def _latest_trade_watermark(db: Phase6Database, symbol: str) -> tuple[datetime | None, str | None]:
    row = db.fetch_one(
        """
        SELECT watermark_ts_utc, watermark_cursor
        FROM ingestion_watermark_history
        WHERE source_name = 'COINAPI'
          AND symbol = :symbol
          AND watermark_kind IN ('BOOTSTRAP_END', 'INCREMENTAL_END')
        ORDER BY watermark_ts_utc DESC
        LIMIT 1
        """,
        {"symbol": symbol},
    )
    if row is None:
        return None, None
    return row["watermark_ts_utc"], row["watermark_cursor"]


def _should_refresh_hourly_bars(last_ts: datetime | None, end_ts: datetime) -> bool:
    if last_ts is None:
        return True
    last_hour = last_ts.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    end_hour = end_ts.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return end_hour > last_hour


def _recent_zero_trade_streak(db: Phase6Database, symbol: str, *, lookback_rows: int) -> int:
    rows = db.fetch_all(
        """
        SELECT records_ingested
        FROM ingestion_watermark_history
        WHERE source_name = 'COINAPI'
          AND symbol = :symbol
          AND watermark_kind = 'INCREMENTAL_END'
        ORDER BY watermark_ts_utc DESC
        LIMIT :lookback_rows
        """,
        {"symbol": symbol, "lookback_rows": lookback_rows},
    )
    streak = 0
    for row in rows:
        ingested = int(row.get("records_ingested") or 0)
        if ingested > 0:
            break
        streak += 1
    return streak



def run_incremental_sync(
    *,
    db: Phase6Database,
    provider: HistoricalProvider,
    symbols: Sequence[str],
    asset_id_by_symbol: dict[str, int],
    local_cache_dir: Path,
    now_utc: datetime,
    quiet_symbol_zero_streak: int = 3,
    quiet_symbol_poll_interval_minutes: int = 5,
) -> IncrementalSyncResult:
    """Run one deterministic incremental ingestion cycle."""
    cycle_id = str(deterministic_uuid("phase6_ingestion_cycle", "incremental", now_utc.isoformat(), len(symbols)))
    db.execute(
        """
        INSERT INTO ingestion_cycle (
            ingestion_cycle_id, cycle_kind, started_at_utc, completed_at_utc,
            status, details_hash, row_hash
        ) VALUES (
            :ingestion_cycle_id, 'INCREMENTAL', :started_at_utc, NULL,
            'RUNNING', :details_hash, :row_hash
        )
        """,
        {
            "ingestion_cycle_id": cycle_id,
            "started_at_utc": now_utc,
            "details_hash": stable_hash(("incremental_start", now_utc.isoformat(), len(symbols))),
            "row_hash": stable_hash(("ingestion_cycle", cycle_id, "RUNNING")),
        },
    )

    symbols_synced = 0
    symbols_throttled = 0
    bars_written = 0
    trades_archived = 0
    ohlcv_api_calls = 0
    trade_api_calls = 0

    for symbol in symbols:
        last_ts, cursor = _latest_trade_watermark(db, symbol)
        start_ts = (last_ts + timedelta(seconds=1)) if last_ts is not None else (now_utc - timedelta(minutes=60))
        end_ts = now_utc
        if end_ts <= start_ts:
            continue
        zero_streak = _recent_zero_trade_streak(db, symbol, lookback_rows=max(quiet_symbol_zero_streak, 1))
        min_poll_minutes = quiet_symbol_poll_interval_minutes if zero_streak >= quiet_symbol_zero_streak else 1
        if last_ts is not None and (end_ts - last_ts) < timedelta(minutes=max(min_poll_minutes, 1)):
            symbols_throttled += 1
            continue

        bars = ()
        if _should_refresh_hourly_bars(last_ts, end_ts):
            bars = provider.fetch_ohlcv(symbol, start_ts, end_ts, "1HRS")
            ohlcv_api_calls += 1
        for bar in bars:
            row_hash = stable_hash(("market_ohlcv_hourly", symbol, bar.hour_ts_utc.isoformat(), str(bar.close_price)))
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
                    "asset_id": asset_id_by_symbol[symbol],
                    "hour_ts_utc": bar.hour_ts_utc,
                    "open_price": bar.open_price,
                    "high_price": bar.high_price,
                    "low_price": bar.low_price,
                    "close_price": bar.close_price,
                    "volume_base": bar.volume_base,
                    "volume_quote": bar.volume_quote,
                    "trade_count": bar.trade_count,
                    "source_venue": bar.source_venue,
                    "ingest_run_id": cycle_id,
                    "row_hash": row_hash,
                },
            )
            bars_written += 1

        trades, next_cursor = provider.fetch_trades(symbol, start_ts, end_ts, cursor)
        trade_api_calls += 1
        chunks = archive_trade_ticks(
            base_dir=local_cache_dir,
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
        trades_archived += len(trades)
        symbols_synced += 1

        db.execute(
            """
            INSERT INTO ingestion_watermark_history (
                ingestion_cycle_id, source_name, symbol,
                watermark_kind, watermark_ts_utc, watermark_cursor,
                records_ingested, row_hash
            ) VALUES (
                :ingestion_cycle_id, 'COINAPI', :symbol,
                'INCREMENTAL_END', :watermark_ts_utc, :watermark_cursor,
                :records_ingested, :row_hash
            )
            """,
            {
                "ingestion_cycle_id": cycle_id,
                "symbol": symbol,
                "watermark_ts_utc": end_ts,
                "watermark_cursor": next_cursor,
                "records_ingested": len(trades),
                "row_hash": stable_hash(("watermark", cycle_id, symbol, end_ts.isoformat(), len(trades))),
            },
        )

    return IncrementalSyncResult(
        ingestion_cycle_id=cycle_id,
        symbols_synced=symbols_synced,
        symbols_throttled=symbols_throttled,
        bars_written=bars_written,
        trades_archived=trades_archived,
        ohlcv_api_calls=ohlcv_api_calls,
        trade_api_calls=trade_api_calls,
    )
