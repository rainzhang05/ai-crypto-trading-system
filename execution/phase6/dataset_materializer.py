"""Tick-canonical dataset materialization with deterministic hash lineage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Sequence

from execution.decision_engine import stable_hash
from execution.phase6.common import Phase6Database, deterministic_uuid


@dataclass(frozen=True)
class DatasetSnapshotResult:
    """Materialized dataset snapshot payload."""

    dataset_snapshot_id: str
    dataset_hash: str
    row_count: int
    symbol_count: int
    output_path: Path



def _load_symbol_trade_frames(base_dir: Path, symbols: Sequence[str]) -> tuple[object, list[tuple[str, str, int]]]:
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas and pyarrow are required for dataset materialization") from exc

    frames: list[pd.DataFrame] = []
    components: list[tuple[str, str, int]] = []
    for symbol in sorted(symbols):
        symbol_root = base_dir / "coinapi" / "trades" / symbol
        if not symbol_root.exists():
            continue
        for partition in sorted(symbol_root.glob("date=*")):
            for parquet_file in sorted(partition.glob("*.parquet")):
                frame = pd.read_parquet(parquet_file)
                frame["symbol"] = symbol
                frame["source_file"] = str(parquet_file)
                frames.append(frame)
                components.append((symbol, str(parquet_file), int(len(frame))))

    if not frames:
        return pd.DataFrame(), components

    merged = pd.concat(frames, ignore_index=True)
    merged["trade_ts_utc"] = pd.to_datetime(merged["trade_ts_utc"], utc=True)
    merged = merged.sort_values(["trade_ts_utc", "symbol", "exchange_trade_id", "price", "size"])
    return merged, components


def materialize_tick_canonical_dataset(
    *,
    db: Phase6Database,
    local_cache_dir: Path,
    symbols: Sequence[str],
    output_dir: Path,
    generated_at_utc: datetime,
) -> DatasetSnapshotResult:
    """Materialize deterministic training dataset from local trade archive."""
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas and pyarrow are required for dataset materialization") from exc

    frame, components = _load_symbol_trade_frames(local_cache_dir, symbols)
    if frame.empty:
        raise RuntimeError("No local trade archive data found for dataset materialization")

    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_id = str(deterministic_uuid("phase6_dataset_snapshot", generated_at_utc.isoformat(), tuple(sorted(symbols))))
    out_path = output_dir / f"dataset_{snapshot_id[:16]}.parquet"
    frame.to_parquet(out_path, index=False)

    component_hash = stable_hash(tuple(token for component in components for token in component))
    dataset_hash = stable_hash(
        (
            "dataset_snapshot",
            snapshot_id,
            generated_at_utc.isoformat(),
            int(len(frame)),
            int(frame["symbol"].nunique()),
            component_hash,
        )
    )

    db.execute(
        """
        INSERT INTO dataset_snapshot (
            dataset_snapshot_id, generated_at_utc, dataset_hash,
            row_count, symbol_count, materialized_path,
            component_hash, row_hash
        ) VALUES (
            :dataset_snapshot_id, :generated_at_utc, :dataset_hash,
            :row_count, :symbol_count, :materialized_path,
            :component_hash, :row_hash
        )
        """,
        {
            "dataset_snapshot_id": snapshot_id,
            "generated_at_utc": generated_at_utc.astimezone(timezone.utc),
            "dataset_hash": dataset_hash,
            "row_count": int(len(frame)),
            "symbol_count": int(frame["symbol"].nunique()),
            "materialized_path": str(out_path),
            "component_hash": component_hash,
            "row_hash": stable_hash(("dataset_snapshot", snapshot_id, dataset_hash)),
        },
    )

    for symbol, file_path, row_count in components:
        db.execute(
            """
            INSERT INTO dataset_snapshot_component (
                dataset_snapshot_id, symbol, component_path,
                component_row_count, component_hash, row_hash
            ) VALUES (
                :dataset_snapshot_id, :symbol, :component_path,
                :component_row_count, :component_hash, :row_hash
            )
            ON CONFLICT (dataset_snapshot_id, symbol, component_path) DO NOTHING
            """,
            {
                "dataset_snapshot_id": snapshot_id,
                "symbol": symbol,
                "component_path": file_path,
                "component_row_count": row_count,
                "component_hash": stable_hash(("dataset_component", snapshot_id, symbol, file_path, row_count)),
                "row_hash": stable_hash(("dataset_component_row", snapshot_id, symbol, file_path)),
            },
        )

    return DatasetSnapshotResult(
        dataset_snapshot_id=snapshot_id,
        dataset_hash=dataset_hash,
        row_count=int(len(frame)),
        symbol_count=int(frame["symbol"].nunique()),
        output_path=out_path,
    )
