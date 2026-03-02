"""Helpers for executing SQL artifact files in integration tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from psycopg.rows import dict_row
import sqlparse


def _remove_psql_meta_commands(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("\\"):
            continue
        lines.append(line)
    return "\n".join(lines)


def split_sql_statements(text: str) -> list[str]:
    cleaned = _remove_psql_meta_commands(text)
    return [statement.strip() for statement in sqlparse.split(cleaned) if statement.strip()]


def execute_sql_file(conn: Any, sql_path: Path) -> list[dict[str, Any]]:
    content = sql_path.read_text(encoding="utf-8")
    statements = split_sql_statements(content)
    results: list[dict[str, Any]] = []

    with conn.cursor(row_factory=dict_row) as cur:
        for statement in statements:
            cur.execute(statement)
            if cur.description is not None:
                results.extend(dict(row) for row in cur.fetchall())
    return results


def assert_check_rows_are_zero(rows: list[dict[str, Any]], *, source: str) -> None:
    check_rows = [row for row in rows if "check_name" in row and "violations" in row]
    assert check_rows, f"No check rows were returned for {source}."
    for row in check_rows:
        assert int(row["violations"]) == 0, (
            f"{source}: {row['check_name']} has violations={row['violations']}"
        )
