"""Gap detection and deterministic repair workflow for Phase 6 ingestion."""

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
class GapRepairResult:
    """Summary for one gap repair run."""

    repaired_count: int
    failed_count: int



def detect_gap_events(
    *,
    db: Phase6Database,
    symbol: str,
    expected_step_minutes: int,
    lookback_hours: int,
) -> int:
    """Detect missing watermark intervals and persist pending gap events."""
    rows = db.fetch_all(
        """
        SELECT watermark_ts_utc
        FROM ingestion_watermark_history
        WHERE source_name = 'COINAPI'
          AND symbol = :symbol
          AND watermark_kind IN ('BOOTSTRAP_END', 'INCREMENTAL_END')
          AND watermark_ts_utc >= :window_start
        ORDER BY watermark_ts_utc ASC
        """,
        {
            "symbol": symbol,
            "window_start": datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours),
        },
    )

    existing_rows = db.fetch_all(
        """
        SELECT gap_start_ts_utc, gap_end_ts_utc
        FROM data_gap_event
        WHERE source_name = 'COINAPI'
          AND symbol = :symbol
          AND gap_start_ts_utc >= :window_start
        """,
        {
            "symbol": symbol,
            "window_start": datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours),
        },
    )
    existing_pairs = {(row["gap_start_ts_utc"], row["gap_end_ts_utc"]) for row in existing_rows}

    inserted = 0
    expected_step = timedelta(minutes=expected_step_minutes)
    for idx in range(1, len(rows)):
        prev_ts = rows[idx - 1]["watermark_ts_utc"]
        curr_ts = rows[idx]["watermark_ts_utc"]
        if curr_ts - prev_ts <= expected_step:
            continue
        if (prev_ts, curr_ts) in existing_pairs:
            continue
        event_id = str(deterministic_uuid("phase6_gap_event", symbol, prev_ts.isoformat(), curr_ts.isoformat()))
        row_hash = stable_hash(("data_gap_event", event_id, symbol, prev_ts.isoformat(), curr_ts.isoformat()))
        db.execute(
            """
            INSERT INTO data_gap_event (
                gap_event_id, source_name, symbol,
                gap_start_ts_utc, gap_end_ts_utc,
                status, detected_at_utc, details_hash, row_hash
            ) VALUES (
                :gap_event_id, 'COINAPI', :symbol,
                :gap_start_ts_utc, :gap_end_ts_utc,
                'PENDING', :detected_at_utc, :details_hash, :row_hash
            )
            ON CONFLICT (gap_event_id) DO NOTHING
            """,
            {
                "gap_event_id": event_id,
                "symbol": symbol,
                "gap_start_ts_utc": prev_ts,
                "gap_end_ts_utc": curr_ts,
                "detected_at_utc": datetime.now(tz=timezone.utc),
                "details_hash": stable_hash(("gap", symbol, prev_ts.isoformat(), curr_ts.isoformat())),
                "row_hash": row_hash,
            },
        )
        existing_pairs.add((prev_ts, curr_ts))
        inserted += 1

    return inserted


def repair_pending_gaps(
    *,
    db: Phase6Database,
    provider: HistoricalProvider,
    local_cache_dir: str,
) -> GapRepairResult:
    """Repair all pending gaps and record deterministic evidence."""
    rows = db.fetch_all(
        """
        SELECT gap_event_id, symbol, gap_start_ts_utc, gap_end_ts_utc
        FROM data_gap_event
        WHERE status = 'PENDING'
        ORDER BY detected_at_utc ASC
        """,
        {},
    )
    terminal_rows = db.fetch_all(
        """
        SELECT symbol, gap_start_ts_utc, gap_end_ts_utc
        FROM data_gap_event
        WHERE status IN ('REPAIRED', 'FAILED')
        """,
        {},
    )
    resolved_pairs = {
        (str(row["symbol"]), row["gap_start_ts_utc"], row["gap_end_ts_utc"])
        for row in terminal_rows
    }

    repaired = 0
    failed = 0

    for row in rows:
        gap_id = str(row["gap_event_id"])
        symbol = str(row["symbol"])
        start_ts = row["gap_start_ts_utc"]
        end_ts = row["gap_end_ts_utc"]
        pair_key = (symbol, start_ts, end_ts)
        if pair_key in resolved_pairs:
            continue
        try:
            trades, _ = provider.fetch_trades(symbol, start_ts, end_ts, None)
            chunks = archive_trade_ticks(
                base_dir=Path(local_cache_dir),
                symbol=symbol,
                source="COINAPI",
                trades=trades,
            )
            persist_trade_chunk_manifest(
                db,
                ingestion_cycle_id=gap_id,
                source="COINAPI",
                symbol=symbol,
                chunks=chunks,
            )
            terminal_id = str(deterministic_uuid("phase6_gap_event_terminal", gap_id, "REPAIRED"))
            db.execute(
                """
                INSERT INTO data_gap_event (
                    gap_event_id, source_name, symbol,
                    gap_start_ts_utc, gap_end_ts_utc,
                    status, detected_at_utc, resolved_at_utc,
                    details_hash, row_hash
                ) VALUES (
                    :gap_event_id, 'COINAPI', :symbol,
                    :gap_start_ts_utc, :gap_end_ts_utc,
                    'REPAIRED', :detected_at_utc, :resolved_at_utc,
                    :details_hash, :row_hash
                )
                ON CONFLICT (gap_event_id) DO NOTHING
                """,
                {
                    "gap_event_id": terminal_id,
                    "symbol": symbol,
                    "gap_start_ts_utc": start_ts,
                    "gap_end_ts_utc": end_ts,
                    "detected_at_utc": datetime.now(tz=timezone.utc),
                    "resolved_at_utc": datetime.now(tz=timezone.utc),
                    "details_hash": stable_hash(("gap_resolution", gap_id, "REPAIRED", len(trades))),
                    "row_hash": stable_hash(("data_gap_event", terminal_id, "REPAIRED", len(trades))),
                },
            )
            repaired += 1
            resolved_pairs.add(pair_key)
        except Exception:
            terminal_id = str(deterministic_uuid("phase6_gap_event_terminal", gap_id, "FAILED"))
            db.execute(
                """
                INSERT INTO data_gap_event (
                    gap_event_id, source_name, symbol,
                    gap_start_ts_utc, gap_end_ts_utc,
                    status, detected_at_utc, resolved_at_utc,
                    details_hash, row_hash
                ) VALUES (
                    :gap_event_id, 'COINAPI', :symbol,
                    :gap_start_ts_utc, :gap_end_ts_utc,
                    'FAILED', :detected_at_utc, :resolved_at_utc,
                    :details_hash, :row_hash
                )
                ON CONFLICT (gap_event_id) DO NOTHING
                """,
                {
                    "gap_event_id": terminal_id,
                    "symbol": symbol,
                    "gap_start_ts_utc": start_ts,
                    "gap_end_ts_utc": end_ts,
                    "detected_at_utc": datetime.now(tz=timezone.utc),
                    "resolved_at_utc": datetime.now(tz=timezone.utc),
                    "details_hash": stable_hash(("gap_resolution", gap_id, "FAILED")),
                    "row_hash": stable_hash(("data_gap_event", terminal_id, "FAILED")),
                },
            )
            failed += 1
            resolved_pairs.add(pair_key)

    return GapRepairResult(repaired_count=repaired, failed_count=failed)
