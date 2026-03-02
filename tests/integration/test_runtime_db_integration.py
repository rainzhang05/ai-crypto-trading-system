"""DB-backed integration tests for Phase 1D runtime execution and replay."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from execution.replay_engine import execute_hour, replay_hour
from tests.utils.runtime_db import (
    PsycopgRuntimeDB,
    deterministic_uuid,
    insert_runtime_fixture,
    preload_open_lot_for_sell_path,
)


def _count_rows(db: PsycopgRuntimeDB, table: str, run_id: str) -> int:
    row = db.fetch_one(
        f"SELECT COUNT(*) AS n FROM {table} WHERE run_id = :run_id",
        {"run_id": run_id},
    )
    return int(row["n"]) if row is not None else 0


def test_execute_hour_success_and_replay_parity(runtime_db: PsycopgRuntimeDB) -> None:
    fixture = insert_runtime_fixture(
        runtime_db,
        seed="int_success",
        prediction_row_hash="4" * 64,  # deterministic_decision => ENTER for fixture hash set
    )
    result = execute_hour(
        db=runtime_db,
        run_id=fixture.run_id,
        account_id=fixture.account_id,
        run_mode="LIVE",
        hour_ts_utc=fixture.hour_ts_utc,
    )
    report = replay_hour(
        db=runtime_db,
        run_id=fixture.run_id,
        account_id=fixture.account_id,
        hour_ts_utc=fixture.hour_ts_utc,
    )

    assert len(result.trade_signals) == 1
    assert len(result.order_requests) == 1
    assert len(result.order_fills) == 1
    assert len(result.position_lots) == 1
    assert len(result.executed_trades) == 0
    assert len(result.risk_events) == 1
    assert report.mismatch_count == 0

    assert _count_rows(runtime_db, "trade_signal", str(fixture.run_id)) == 1
    assert _count_rows(runtime_db, "order_request", str(fixture.run_id)) == 1
    assert _count_rows(runtime_db, "order_fill", str(fixture.run_id)) == 1
    assert _count_rows(runtime_db, "position_lot", str(fixture.run_id)) == 1
    assert _count_rows(runtime_db, "executed_trade", str(fixture.run_id)) == 0
    assert _count_rows(runtime_db, "risk_event", str(fixture.run_id)) == 1

    hash_row = runtime_db.fetch_one(
        """
        SELECT
            SUM(CASE WHEN row_hash IS NULL THEN 1 ELSE 0 END) AS signal_null_hashes
        FROM trade_signal
        WHERE run_id = :run_id
        """,
        {"run_id": str(fixture.run_id)},
    )
    assert hash_row is not None
    assert int(hash_row["signal_null_hashes"]) == 0

    with pytest.raises(Exception):
        runtime_db.execute(
            """
            UPDATE trade_signal
            SET direction = 'FLAT'
            WHERE run_id = :run_id
            """,
            {"run_id": str(fixture.run_id)},
        )
        runtime_db.conn.commit()
    runtime_db.conn.rollback()

    causality_row = runtime_db.fetch_one(
        """
        SELECT COUNT(*) AS violations
        FROM order_fill f
        JOIN order_request r
          ON r.order_id = f.order_id
         AND r.run_id = f.run_id
         AND r.run_mode = f.run_mode
         AND r.account_id = f.account_id
        WHERE f.run_id = :run_id
          AND f.fill_ts_utc < r.request_ts_utc
        """,
        {"run_id": str(fixture.run_id)},
    )
    assert causality_row is not None
    assert int(causality_row["violations"]) == 0


def test_activation_gate_revoked_blocks_order_and_logs_risk_event(runtime_db: PsycopgRuntimeDB) -> None:
    fixture = insert_runtime_fixture(
        runtime_db,
        seed="int_activation_revoked",
        activation_status="APPROVED",
        activation_window_end_utc=datetime(2099, 1, 1, tzinfo=timezone.utc),
        prediction_row_hash="4" * 64,
    )
    result = execute_hour(
        db=runtime_db,
        run_id=fixture.run_id,
        account_id=fixture.account_id,
        run_mode="LIVE",
        hour_ts_utc=fixture.hour_ts_utc,
    )
    assert len(result.order_requests) == 0
    assert len(result.risk_events) >= 1

    row = runtime_db.fetch_one(
        """
        SELECT COUNT(*) AS n
        FROM risk_event
        WHERE run_id = :run_id
          AND reason_code = 'ACTIVATION_WINDOW_NOT_REACHED'
        """,
        {"run_id": str(fixture.run_id)},
    )
    assert row is not None
    assert int(row["n"]) >= 1


def test_cluster_cap_violation_blocks_order_and_logs_risk_event(runtime_db: PsycopgRuntimeDB) -> None:
    fixture = insert_runtime_fixture(
        runtime_db,
        seed="int_cluster_cap",
        cluster_exposure_pct=Decimal("0.0790000000"),
        prediction_row_hash="4" * 64,
    )
    result = execute_hour(
        db=runtime_db,
        run_id=fixture.run_id,
        account_id=fixture.account_id,
        run_mode="LIVE",
        hour_ts_utc=fixture.hour_ts_utc,
    )
    assert len(result.order_requests) == 0
    assert len(result.risk_events) >= 1
    row = runtime_db.fetch_one(
        """
        SELECT COUNT(*) AS n
        FROM risk_event
        WHERE run_id = :run_id
          AND reason_code = 'CLUSTER_CAP_EXCEEDED'
        """,
        {"run_id": str(fixture.run_id)},
    )
    assert row is not None
    assert int(row["n"]) >= 1


def test_runtime_risk_gate_halt_blocks_order_and_logs_risk_event(runtime_db: PsycopgRuntimeDB) -> None:
    fixture = insert_runtime_fixture(
        runtime_db,
        seed="int_halt_gate",
        halt_new_entries=True,
        prediction_row_hash="4" * 64,
    )
    result = execute_hour(
        db=runtime_db,
        run_id=fixture.run_id,
        account_id=fixture.account_id,
        run_mode="LIVE",
        hour_ts_utc=fixture.hour_ts_utc,
    )
    assert len(result.order_requests) == 0
    assert len(result.risk_events) >= 1
    row = runtime_db.fetch_one(
        """
        SELECT COUNT(*) AS n
        FROM risk_event
        WHERE run_id = :run_id
          AND reason_code = 'HALT_NEW_ENTRIES_ACTIVE'
        """,
        {"run_id": str(fixture.run_id)},
    )
    assert row is not None
    assert int(row["n"]) >= 1


def test_parent_hash_mismatch_aborts_insert_without_partial_writes(runtime_db: PsycopgRuntimeDB) -> None:
    run_id = deterministic_uuid("run-int_parent_hash")
    with pytest.raises(Exception, match="cluster_exposure parent hash mismatch"):
        insert_runtime_fixture(
            runtime_db,
            seed="int_parent_hash",
            cluster_parent_hash="x" * 64,
            risk_row_hash="r" * 64,
        )
    runtime_db.conn.rollback()

    assert _count_rows(runtime_db, "trade_signal", str(run_id)) == 0
    assert _count_rows(runtime_db, "order_request", str(run_id)) == 0
    assert _count_rows(runtime_db, "risk_event", str(run_id)) == 0

    run_ctx_rows = runtime_db.fetch_one(
        "SELECT COUNT(*) AS n FROM run_context WHERE run_id = :run_id",
        {"run_id": str(run_id)},
    )
    assert run_ctx_rows is not None
    assert int(run_ctx_rows["n"]) == 0


def test_exit_path_with_preloaded_lot_persists_executed_trade(runtime_db: PsycopgRuntimeDB) -> None:
    fixture = insert_runtime_fixture(
        runtime_db,
        seed="int_exit_with_lot",
        prediction_row_hash="3" * 64,  # deterministic_decision => EXIT
        expected_return=Decimal("-0.020000000000000000"),
    )
    preload_open_lot_for_sell_path(runtime_db, fixture, seed="int_exit_with_lot")

    result = execute_hour(
        db=runtime_db,
        run_id=fixture.run_id,
        account_id=fixture.account_id,
        run_mode="LIVE",
        hour_ts_utc=fixture.hour_ts_utc,
    )
    assert len(result.order_requests) >= 1
    assert all(order.side == "SELL" for order in result.order_requests)
    assert len(result.order_fills) >= 1
    assert len(result.executed_trades) >= 1

    count_row = runtime_db.fetch_one(
        "SELECT COUNT(*) AS n FROM executed_trade WHERE run_id = :run_id",
        {"run_id": str(fixture.run_id)},
    )
    assert count_row is not None
    assert int(count_row["n"]) >= 1


def test_exit_path_without_lots_emits_no_shorting_guard(runtime_db: PsycopgRuntimeDB) -> None:
    fixture = insert_runtime_fixture(
        runtime_db,
        seed="int_exit_without_lots",
        prediction_row_hash="3" * 64,  # deterministic_decision => EXIT
        expected_return=Decimal("-0.020000000000000000"),
    )
    result = execute_hour(
        db=runtime_db,
        run_id=fixture.run_id,
        account_id=fixture.account_id,
        run_mode="LIVE",
        hour_ts_utc=fixture.hour_ts_utc,
    )
    assert len(result.order_requests) >= 1
    assert all(order.side == "SELL" for order in result.order_requests)
    assert len(result.executed_trades) == 0
    assert any(event.reason_code == "SELL_ALLOCATION_INSUFFICIENT_LOTS" for event in result.risk_events)
