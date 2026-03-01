"""Integration tests for governance SQL validation gates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from psycopg.rows import dict_row


def _split_sql_statements(content: str) -> list[str]:
    cleaned_lines = [line for line in content.splitlines() if not line.strip().startswith("--")]
    cleaned_content = "\n".join(cleaned_lines)

    statements: list[str] = []
    parts = cleaned_content.split(";")
    for part in parts:
        stmt = part.strip()
        if not stmt:
            continue
        statements.append(stmt + ";")
    return statements


def _run_validation_sql(conn: Any, sql_path: Path) -> list[dict[str, Any]]:
    content = sql_path.read_text(encoding="utf-8")
    statements = _split_sql_statements(content)
    results: list[dict[str, Any]] = []
    with conn.cursor(row_factory=dict_row) as cur:
        for statement in statements:
            cur.execute(statement)
            rows = cur.fetchall()
            for row in rows:
                if "check_name" in row and "violations" in row:
                    results.append(dict(row))
    conn.rollback()
    return results


def test_phase_1c_validation_sql_returns_zero(pg_conn: Any) -> None:
    sql_path = Path("governance/PHASE_1C_VALIDATION.sql")
    results = _run_validation_sql(pg_conn, sql_path)
    assert results, "No check rows were returned by Phase 1C validation SQL."
    for row in results:
        assert int(row["violations"]) == 0, f"{row['check_name']} has violations={row['violations']}"


def test_phase_1d_validation_sql_returns_zero(pg_conn: Any) -> None:
    sql_path = Path("governance/PHASE_1D_RUNTIME_VALIDATION.sql")
    results = _run_validation_sql(pg_conn, sql_path)
    assert results, "No check rows were returned by Phase 1D validation SQL."
    for row in results:
        assert int(row["violations"]) == 0, f"{row['check_name']} has violations={row['violations']}"
