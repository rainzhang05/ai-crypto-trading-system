"""DB-backed integration tests for Phase 2 replay harness."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

import pytest

from execution.deterministic_context import DeterministicAbortError
from execution.replay_harness import (
    load_snapshot_boundary,
    recompute_hash_dag,
    replay_manifest_parity,
    replay_manifest_window_parity,
)
from tests.utils.runtime_db import PsycopgRuntimeDB, insert_runtime_fixture


def _align_manifest_to_recomputed_root(
    db: PsycopgRuntimeDB,
    run_id: UUID,
    account_id: int,
    hour_ts_utc: datetime,
) -> None:
    boundary = load_snapshot_boundary(
        db=db,
        run_id=run_id,
        account_id=account_id,
        origin_hour_ts_utc=hour_ts_utc,
    )
    recomputed = recompute_hash_dag(db=db, boundary=boundary)
    db.execute(
        """
        UPDATE run_context
        SET replay_root_hash = :replay_root_hash
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :origin_hour_ts_utc
        """,
        {
            "replay_root_hash": recomputed.root_hash,
            "run_id": str(run_id),
            "account_id": account_id,
            "origin_hour_ts_utc": hour_ts_utc,
        },
    )
    db.execute(
        """
        UPDATE replay_manifest
        SET replay_root_hash = :replay_root_hash,
            authoritative_row_count = :authoritative_row_count
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :origin_hour_ts_utc
        """,
        {
            "replay_root_hash": recomputed.root_hash,
            "authoritative_row_count": recomputed.authoritative_row_count,
            "run_id": str(run_id),
            "account_id": account_id,
            "origin_hour_ts_utc": hour_ts_utc,
        },
    )
    db.conn.commit()


def test_replay_manifest_parity_detects_mismatch_without_alignment(runtime_db: PsycopgRuntimeDB) -> None:
    fixture = insert_runtime_fixture(runtime_db, seed="phase2_manifest_mismatch")
    report = replay_manifest_parity(
        db=runtime_db,
        run_id=fixture.run_id,
        account_id=fixture.account_id,
        origin_hour_ts_utc=fixture.hour_ts_utc,
    )
    assert report.replay_parity is False
    assert report.mismatch_count >= 1
    assert any(
        failure.failure_code in {"ROOT_HASH_MISMATCH", "RUN_CONTEXT_ROOT_MISMATCH"}
        for failure in report.failures
    )


def test_replay_manifest_parity_passes_after_alignment(runtime_db: PsycopgRuntimeDB) -> None:
    fixture = insert_runtime_fixture(runtime_db, seed="phase2_manifest_pass")
    _align_manifest_to_recomputed_root(
        db=runtime_db,
        run_id=fixture.run_id,
        account_id=fixture.account_id,
        hour_ts_utc=fixture.hour_ts_utc,
    )
    report = replay_manifest_parity(
        db=runtime_db,
        run_id=fixture.run_id,
        account_id=fixture.account_id,
        origin_hour_ts_utc=fixture.hour_ts_utc,
    )
    assert report.replay_parity is True
    assert report.mismatch_count == 0


def test_replay_manifest_window_parity_single_target(runtime_db: PsycopgRuntimeDB) -> None:
    fixture = insert_runtime_fixture(runtime_db, seed="phase2_window_single")
    _align_manifest_to_recomputed_root(
        db=runtime_db,
        run_id=fixture.run_id,
        account_id=fixture.account_id,
        hour_ts_utc=fixture.hour_ts_utc,
    )
    report = replay_manifest_window_parity(
        db=runtime_db,
        account_id=fixture.account_id,
        run_mode="LIVE",
        start_hour_ts_utc=fixture.hour_ts_utc,
        end_hour_ts_utc=fixture.hour_ts_utc,
    )
    assert report.replay_parity is True
    assert report.total_targets == 1
    assert report.passed_targets == 1
    assert report.failed_targets == 0
    assert str(report.items[0].target.run_id) == str(fixture.run_id)


def test_replay_manifest_window_parity_no_targets_aborts(runtime_db: PsycopgRuntimeDB) -> None:
    fixture = insert_runtime_fixture(runtime_db, seed="phase2_window_empty")
    with pytest.raises(DeterministicAbortError, match="No run_context rows found for replay target window"):
        replay_manifest_window_parity(
            db=runtime_db,
            account_id=fixture.account_id,
            run_mode="LIVE",
            start_hour_ts_utc=fixture.hour_ts_utc + timedelta(days=30),
            end_hour_ts_utc=fixture.hour_ts_utc + timedelta(days=30, hours=1),
        )
