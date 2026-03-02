from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from execution.phase6.bootstrap_backfill import _persist_ohlcv_rows, run_bootstrap_backfill
from execution.phase6.gap_repair import detect_gap_events, repair_pending_gaps
from execution.phase6.incremental_sync import _latest_trade_watermark, run_incremental_sync
from execution.phase6.provider_contract import OhlcvBar, TradeTick
from execution.phase6.trade_archive import RawTradeChunk
from tests.phase6.utils import FakeDB


class _Provider:
    def __init__(self) -> None:
        self.trade_calls = 0

    def fetch_ohlcv(self, symbol, start_ts_utc, end_ts_utc, granularity):  # type: ignore[no-untyped-def]
        return (
            OhlcvBar(
                symbol=symbol,
                source_venue="COINAPI",
                hour_ts_utc=start_ts_utc.replace(minute=0, second=0, microsecond=0),
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
        self.trade_calls += 1
        trade = TradeTick(
            symbol=symbol,
            source_venue="COINAPI",
            trade_ts_utc=start_ts_utc,
            exchange_trade_id=f"{symbol}-{self.trade_calls}",
            price=Decimal("1"),
            size=Decimal("1"),
            side="BUY",
        )
        if self.trade_calls % 2 == 1:
            return (trade,), "next"
        return (trade,), None


def test_bootstrap_backfill_invalid_window() -> None:
    with pytest.raises(RuntimeError, match="end_ts_utc > start_ts_utc"):
        run_bootstrap_backfill(
            db=FakeDB(),
            provider=_Provider(),
            universe_symbols=("BTC",),
            asset_id_by_symbol={"BTC": 1},
            local_cache_dir=".",
            start_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_bootstrap_backfill_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = FakeDB()
    provider = _Provider()
    fake_chunk = RawTradeChunk(
        symbol="BTC",
        day_utc="2026-01-01",
        file_path=tmp_path / "a.parquet",
        row_count=1,
        min_trade_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        max_trade_ts_utc=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        file_sha256="a" * 64,
        chunk_hash="b" * 64,
    )
    monkeypatch.setattr(
        "execution.phase6.bootstrap_backfill.archive_trade_ticks",
        lambda **_kwargs: (fake_chunk,),
    )
    monkeypatch.setattr(
        "execution.phase6.bootstrap_backfill.persist_trade_chunk_manifest",
        lambda *_args, **_kwargs: None,
    )

    result = run_bootstrap_backfill(
        db=db,
        provider=provider,
        universe_symbols=("BTC",),
        asset_id_by_symbol={"BTC": 1},
        local_cache_dir=str(tmp_path),
        start_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_ts_utc=datetime(2026, 1, 10, tzinfo=timezone.utc),
    )
    assert result.completed is True
    assert result.symbols_completed == 1
    assert result.bars_written >= 1
    assert result.trades_archived >= 1
    assert len(db.executed) >= 4


def test_persist_ohlcv_rows_empty_and_nonempty() -> None:
    db = FakeDB()
    assert _persist_ohlcv_rows(db, ingest_run_id="r1", asset_id=1, bars=()) == 0
    assert len(db.executed) == 0

    bars = (
        OhlcvBar(
            symbol="BTC",
            source_venue="COINAPI",
            hour_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
            open_price=Decimal("1"),
            high_price=Decimal("2"),
            low_price=Decimal("0.5"),
            close_price=Decimal("1.5"),
            volume_base=Decimal("10"),
            volume_quote=Decimal("12"),
            trade_count=3,
        ),
    )
    assert _persist_ohlcv_rows(db, ingest_run_id="r2", asset_id=1, bars=bars) == 1
    assert len(db.executed) == 1


def test_latest_trade_watermark_branches() -> None:
    db_none = FakeDB()
    assert _latest_trade_watermark(db_none, "BTC") == (None, None)

    db = FakeDB()
    db.set_one("FROM ingestion_watermark_history", {"watermark_ts_utc": datetime(2026, 1, 1, tzinfo=timezone.utc), "watermark_cursor": "c1"})
    ts, cursor = _latest_trade_watermark(db, "BTC")
    assert ts is not None
    assert cursor == "c1"


def test_incremental_sync_success_and_skip_branch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = FakeDB()
    now_utc = datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)
    db.set_one(
        "FROM ingestion_watermark_history",
        {"watermark_ts_utc": now_utc, "watermark_cursor": None},
    )
    monkeypatch.setattr("execution.phase6.incremental_sync.archive_trade_ticks", lambda **_kwargs: ())
    monkeypatch.setattr("execution.phase6.incremental_sync.persist_trade_chunk_manifest", lambda *_args, **_kwargs: None)

    provider = _Provider()
    result = run_incremental_sync(
        db=db,
        provider=provider,
        symbols=("BTC",),
        asset_id_by_symbol={"BTC": 1},
        local_cache_dir=tmp_path,
        now_utc=now_utc,
    )
    # watermark at now_utc causes skip path for this symbol
    assert result.symbols_synced == 0
    assert result.bars_written == 0

    db2 = FakeDB()
    provider2 = _Provider()
    result2 = run_incremental_sync(
        db=db2,
        provider=provider2,
        symbols=("BTC",),
        asset_id_by_symbol={"BTC": 1},
        local_cache_dir=tmp_path,
        now_utc=now_utc,
    )
    assert result2.symbols_synced == 1
    assert result2.bars_written >= 1
    assert result2.trades_archived >= 1


def test_detect_gap_events_and_repair_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = FakeDB()
    base = datetime.now(tz=timezone.utc).replace(second=0, microsecond=0)
    db.set_all(
        "FROM ingestion_watermark_history",
        [
            {"watermark_ts_utc": base},
            {"watermark_ts_utc": base + timedelta(minutes=1)},
            {"watermark_ts_utc": base + timedelta(minutes=10)},
        ],
    )
    inserted = detect_gap_events(db=db, symbol="BTC", expected_step_minutes=1, lookback_hours=24)
    assert inserted == 1
    assert len(db.executed) == 1

    pending_db = FakeDB()
    pending_db.set_all(
        "FROM data_gap_event",
        [
            {
                "gap_event_id": "g1",
                "symbol": "BTC",
                "gap_start_ts_utc": base,
                "gap_end_ts_utc": base + timedelta(minutes=5),
            },
            {
                "gap_event_id": "g2",
                "symbol": "ETH",
                "gap_start_ts_utc": base,
                "gap_end_ts_utc": base + timedelta(minutes=5),
            },
        ],
    )

    class _RepairProvider:
        def __init__(self) -> None:
            self.calls = 0

        def fetch_trades(self, symbol, start_ts_utc, end_ts_utc, cursor):  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("boom")
            return (
                (
                    TradeTick(
                        symbol=symbol,
                        source_venue="COINAPI",
                        trade_ts_utc=start_ts_utc,
                        exchange_trade_id="x",
                        price=Decimal("1"),
                        size=Decimal("1"),
                        side="BUY",
                    ),
                ),
                None,
            )

    monkeypatch.setattr("execution.phase6.gap_repair.archive_trade_ticks", lambda **_kwargs: ())
    monkeypatch.setattr("execution.phase6.gap_repair.persist_trade_chunk_manifest", lambda *_args, **_kwargs: None)

    result = repair_pending_gaps(db=pending_db, provider=_RepairProvider(), local_cache_dir=str(tmp_path))
    assert result.repaired_count == 1
    assert result.failed_count == 1
