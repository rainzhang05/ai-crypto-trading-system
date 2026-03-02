from __future__ import annotations

import builtins
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from execution.phase6.dataset_materializer import _load_symbol_trade_frames, materialize_tick_canonical_dataset
from execution.phase6.feature_pipeline import build_tick_features
from execution.phase6.label_builder import build_horizon_labels
from execution.phase6.provider_contract import TradeTick
from execution.phase6.trade_archive import archive_trade_ticks, persist_trade_chunk_manifest
from tests.phase6.utils import FakeDB


def _trade(symbol: str, ts: datetime, trade_id: str, price: str, size: str, side: str = "BUY") -> TradeTick:
    return TradeTick(
        symbol=symbol,
        source_venue="COINAPI",
        trade_ts_utc=ts,
        exchange_trade_id=trade_id,
        price=Decimal(price),
        size=Decimal(size),
        side=side,
    )


def _raise_missing_import(monkeypatch: pytest.MonkeyPatch, module_name: str) -> None:
    original_import = builtins.__import__

    def _patched(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == module_name:
            raise ImportError(module_name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _patched)


def test_trade_archive_empty_and_import_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _raise_missing_import(monkeypatch, "pandas")
    with pytest.raises(RuntimeError, match="pandas and pyarrow"):
        archive_trade_ticks(base_dir=tmp_path, symbol="BTC", source="COINAPI", trades=())


def test_trade_archive_no_trades_returns_empty(tmp_path: Path) -> None:
    assert archive_trade_ticks(base_dir=tmp_path, symbol="BTC", source="COINAPI", trades=()) == ()


def test_trade_archive_and_manifest_persistence(tmp_path: Path) -> None:
    base_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    trades = (
        _trade("BTC", base_ts + timedelta(seconds=1), "2", "1.2", "3", "SELL"),
        _trade("BTC", base_ts, "1", "1.1", "2", "BUY"),
    )
    chunks = archive_trade_ticks(base_dir=tmp_path, symbol="BTC", source="COINAPI", trades=trades)
    assert len(chunks) == 1
    assert chunks[0].row_count == 2
    assert chunks[0].file_path.exists()
    assert len(chunks[0].file_sha256) == 64

    db = FakeDB()
    persist_trade_chunk_manifest(db, ingestion_cycle_id="cycle-1", source="COINAPI", symbol="BTC", chunks=chunks)
    assert len(db.executed) == 1

    db_empty = FakeDB()
    persist_trade_chunk_manifest(db_empty, ingestion_cycle_id="cycle-1", source="COINAPI", symbol="BTC", chunks=())
    assert db_empty.executed == []


def test_dataset_materializer_no_data_and_import_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _raise_missing_import(monkeypatch, "pandas")
    with pytest.raises(RuntimeError, match="pandas and pyarrow"):
        _load_symbol_trade_frames(tmp_path, ("BTC",))

    monkeypatch.undo()
    _raise_missing_import(monkeypatch, "pandas")
    with pytest.raises(RuntimeError, match="pandas and pyarrow"):
        materialize_tick_canonical_dataset(
            db=FakeDB(),
            local_cache_dir=tmp_path,
            symbols=("BTC",),
            output_dir=tmp_path / "out",
            generated_at_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    monkeypatch.undo()
    db = FakeDB()
    with pytest.raises(RuntimeError, match="No local trade archive data"):
        materialize_tick_canonical_dataset(
            db=db,
            local_cache_dir=tmp_path,
            symbols=("BTC",),
            output_dir=tmp_path / "out",
            generated_at_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_dataset_materializer_success(tmp_path: Path) -> None:
    base_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    trades = (
        _trade("BTC", base_ts, "1", "1.1", "2", "BUY"),
        _trade("BTC", base_ts + timedelta(seconds=1), "2", "1.2", "3", "SELL"),
        _trade("ETH", base_ts, "1", "2.1", "4", "BUY"),
    )
    archive_trade_ticks(base_dir=tmp_path, symbol="BTC", source="COINAPI", trades=trades[:2])
    archive_trade_ticks(base_dir=tmp_path, symbol="ETH", source="COINAPI", trades=trades[2:])

    db = FakeDB()
    result = materialize_tick_canonical_dataset(
        db=db,
        local_cache_dir=tmp_path,
        symbols=("BTC", "ETH"),
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert result.row_count == 3
    assert result.symbol_count == 2
    assert result.output_path.exists()
    assert len(db.executed) == 1 + 2


def test_feature_pipeline_and_labels_success_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    _raise_missing_import(monkeypatch, "numpy")
    with pytest.raises(RuntimeError, match="numpy and pandas"):
        build_tick_features(pd.DataFrame({"x": [1]}))
    monkeypatch.undo()

    with pytest.raises(RuntimeError, match="Dataset is empty"):
        build_tick_features(pd.DataFrame())

    # Build enough rows to satisfy H1/H4/H24 horizons and produce non-empty labels.
    rows = []
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for idx in range(1500):
        rows.append(
            {
                "symbol": "BTC",
                "trade_ts_utc": base + timedelta(minutes=idx),
                "exchange_trade_id": str(idx),
                "price": float(100 + idx * 0.01),
                "size": float(1 + (idx % 3)),
                "side": "BUY" if idx % 2 == 0 else "SELL",
            }
        )
    frame = pd.DataFrame(rows)
    features = build_tick_features(frame)
    assert "roll_vol_32" in features.frame.columns
    assert features.feature_hash

    _raise_missing_import(monkeypatch, "pandas")
    with pytest.raises(RuntimeError, match="pandas is required"):
        build_horizon_labels(features.frame)
    monkeypatch.undo()

    with pytest.raises(RuntimeError, match="Feature frame is empty"):
        build_horizon_labels(pd.DataFrame())

    labels = build_horizon_labels(features.frame)
    assert not labels.frame.empty
    assert labels.label_hash
