"""Walk-forward fold generation for Phase 6B orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

from execution.decision_engine import stable_hash


@dataclass(frozen=True)
class FoldWindow:
    """Train/validation fold definition."""

    fold_index: int
    train_start_utc: datetime
    train_end_utc: datetime
    valid_start_utc: datetime
    valid_end_utc: datetime
    fold_hash: str



def generate_walk_forward_folds(
    *,
    start_utc: datetime,
    end_utc: datetime,
    train_days: int,
    valid_days: int,
    step_days: int,
) -> tuple[FoldWindow, ...]:
    """Generate deterministic rolling walk-forward folds."""
    if end_utc <= start_utc:
        raise RuntimeError("end_utc must be greater than start_utc")
    if min(train_days, valid_days, step_days) <= 0:
        raise RuntimeError("train_days, valid_days, and step_days must be positive")

    folds: list[FoldWindow] = []
    cursor = start_utc.astimezone(timezone.utc)
    fold_index = 0
    train_span = timedelta(days=train_days)
    valid_span = timedelta(days=valid_days)
    step_span = timedelta(days=step_days)

    while True:
        train_start = cursor
        train_end = train_start + train_span
        valid_start = train_end
        valid_end = valid_start + valid_span
        if valid_end > end_utc:
            break

        fold_hash = stable_hash(
            (
                "walk_forward_fold",
                fold_index,
                train_start.isoformat(),
                train_end.isoformat(),
                valid_start.isoformat(),
                valid_end.isoformat(),
            )
        )
        folds.append(
            FoldWindow(
                fold_index=fold_index,
                train_start_utc=train_start,
                train_end_utc=train_end,
                valid_start_utc=valid_start,
                valid_end_utc=valid_end,
                fold_hash=fold_hash,
            )
        )
        fold_index += 1
        cursor = cursor + step_span

    if not folds:
        raise RuntimeError("No walk-forward folds generated for provided window")

    return tuple(folds)
