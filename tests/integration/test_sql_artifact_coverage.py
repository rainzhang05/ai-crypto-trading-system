"""Integration coverage checks for repository SQL executable artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4
import os

import psycopg
from psycopg import sql
import pytest

from tests.utils.executable_artifact_manifest import (
    ROOT,
    SQL_EQUIVALENCE_PAIRS,
    SQL_EXECUTE_SET,
    SQL_EXCLUDED_SET,
)
from tests.utils.sql_artifact_runner import assert_check_rows_are_zero, execute_sql_file


def _db_env_or_skip() -> tuple[str, str, str, str]:
    host = os.getenv("TEST_DB_HOST")
    port = os.getenv("TEST_DB_PORT")
    user = os.getenv("TEST_DB_USER")
    password = os.getenv("TEST_DB_PASSWORD")
    if not all([host, port, user, password]):
        pytest.skip("Integration DB env vars are missing; run via ./scripts/test_all.sh")
    return host or "", port or "", user or "", password or ""


@pytest.fixture(scope="module")
def sql_artifact_conn() -> Iterator[Any]:
    host, port, user, password = _db_env_or_skip()
    scratch_db = f"sql_artifact_cov_{uuid4().hex[:10]}"

    with psycopg.connect(
        host=host,
        port=port,
        dbname="postgres",
        user=user,
        password=password,
        autocommit=True,
    ) as admin_conn:
        with admin_conn.cursor() as cur:
            cur.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(scratch_db))
            )
            cur.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(scratch_db))
            )

    conn = psycopg.connect(
        host=host,
        port=port,
        dbname=scratch_db,
        user=user,
        password=password,
        autocommit=False,
    )
    try:
        yield conn
    finally:
        conn.close()
        with psycopg.connect(
            host=host,
            port=port,
            dbname="postgres",
            user=user,
            password=password,
            autocommit=True,
        ) as admin_conn:
            with admin_conn.cursor() as cur:
                cur.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(scratch_db))
                )


def test_sql_execute_set_runs_and_returns_expected_checks(sql_artifact_conn: Any) -> None:
    bootstrap = ROOT / "schema_bootstrap.sql"
    assert "schema_bootstrap.sql" in SQL_EXECUTE_SET

    execute_sql_file(sql_artifact_conn, bootstrap)
    sql_artifact_conn.commit()
    with sql_artifact_conn.cursor() as cur:
        # schema_bootstrap.sql intentionally clears search_path; repair/validation
        # artifacts are written with unqualified object names.
        cur.execute("SET search_path TO public;")
    sql_artifact_conn.commit()

    repair_schema_rows = execute_sql_file(
        sql_artifact_conn,
        ROOT / "docs/repairs/PHASE_1C_REVISION_C_SCHEMA_REPAIR_BLUEPRINT.sql",
    )
    assert repair_schema_rows == []
    sql_artifact_conn.commit()

    repair_trigger_rows = execute_sql_file(
        sql_artifact_conn,
        ROOT / "docs/repairs/PHASE_1C_REVISION_C_TRIGGER_REPAIR.sql",
    )
    sql_artifact_conn.commit()
    trigger_v2_rows = [
        row for row in repair_trigger_rows if "triggers_with_v2_refs" in row
    ]
    assert trigger_v2_rows, "Repair trigger script did not return triggers_with_v2_refs rows."
    assert int(trigger_v2_rows[-1]["triggers_with_v2_refs"]) == 0

    for relative_path in (
        "docs/validations/PHASE_1C_VALIDATION.sql",
        "docs/validations/PHASE_1D_RUNTIME_VALIDATION.sql",
        "docs/validations/PHASE_2_REPLAY_HARNESS_VALIDATION.sql",
        "docs/validations/PHASE_3_RUNTIME_VALIDATION.sql",
        "docs/validations/PHASE_4_ORDER_LIFECYCLE_VALIDATION.sql",
        "docs/validations/PHASE_5_PORTFOLIO_LEDGER_VALIDATION.sql",
        "docs/validations/PHASE_6A_DATA_TRAINING_VALIDATION.sql",
        "docs/validations/PHASE_6B_BACKTEST_ORCHESTRATOR_VALIDATION.sql",
        "docs/validations/TEST_RUNTIME_INSERT_ENABLE.sql",
    ):
        rows = execute_sql_file(sql_artifact_conn, ROOT / relative_path)
        assert_check_rows_are_zero(rows, source=relative_path)
        sql_artifact_conn.commit()

    executed = {
        "schema_bootstrap.sql",
        "docs/repairs/PHASE_1C_REVISION_C_SCHEMA_REPAIR_BLUEPRINT.sql",
        "docs/repairs/PHASE_1C_REVISION_C_TRIGGER_REPAIR.sql",
        "docs/validations/PHASE_1C_VALIDATION.sql",
        "docs/validations/PHASE_1D_RUNTIME_VALIDATION.sql",
        "docs/validations/PHASE_2_REPLAY_HARNESS_VALIDATION.sql",
        "docs/validations/PHASE_3_RUNTIME_VALIDATION.sql",
        "docs/validations/PHASE_4_ORDER_LIFECYCLE_VALIDATION.sql",
        "docs/validations/PHASE_5_PORTFOLIO_LEDGER_VALIDATION.sql",
        "docs/validations/PHASE_6A_DATA_TRAINING_VALIDATION.sql",
        "docs/validations/PHASE_6B_BACKTEST_ORCHESTRATOR_VALIDATION.sql",
        "docs/validations/TEST_RUNTIME_INSERT_ENABLE.sql",
    }
    assert executed == set(SQL_EXECUTE_SET)


def test_sql_duplicate_phase_files_match_canonical_repairs() -> None:
    for duplicate, canonical in SQL_EQUIVALENCE_PAIRS:
        duplicate_text = (ROOT / duplicate).read_text(encoding="utf-8")
        canonical_text = (ROOT / canonical).read_text(encoding="utf-8")
        assert duplicate_text == canonical_text, (
            "Duplicate SQL file diverged from canonical repair artifact: "
            f"duplicate={duplicate}, canonical={canonical}"
        )


def test_sql_excluded_artifact_policy() -> None:
    assert SQL_EXCLUDED_SET == {"docs/test_logs/live_schema.sql"}
    for excluded in SQL_EXCLUDED_SET:
        assert (ROOT / excluded).exists(), f"Excluded SQL artifact path does not exist: {excluded}"
        assert excluded not in SQL_EXECUTE_SET, f"Excluded SQL artifact appears in execute set: {excluded}"
