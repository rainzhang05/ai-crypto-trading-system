"""Schema contract alignment checks for ORM metadata surfaces."""

from __future__ import annotations

import re
from pathlib import Path

import backend.db.models  # noqa: F401  # Ensure all mapped classes are registered.
from backend.db.base import Base


def _ddl_non_archive_columns() -> dict[str, set[str]]:
    sql = Path("schema_bootstrap.sql").read_text(encoding="utf-8")
    pattern = re.compile(r"CREATE TABLE public\.(\w+) \((.*?)\);", re.S)

    tables: dict[str, set[str]] = {}
    for table_name, body in pattern.findall(sql):
        if table_name.endswith("_phase1a_archive"):
            continue

        columns: set[str] = set()
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("CONSTRAINT"):
                continue
            column_name = line.split()[0].rstrip(",")
            columns.add(column_name)

        tables[table_name] = columns

    return tables


def test_orm_tables_and_columns_match_canonical_schema_contract() -> None:
    """ORM models must cover all non-archive canonical tables/columns exactly."""

    ddl = _ddl_non_archive_columns()
    mapped_tables = Base.metadata.tables

    missing_table_models = sorted(set(ddl) - set(mapped_tables))
    unexpected_mapped_tables = sorted(set(mapped_tables) - set(ddl))

    assert missing_table_models == [], (
        "Missing ORM models for canonical non-archive tables: "
        f"{missing_table_models}"
    )
    assert unexpected_mapped_tables == [], (
        "Mapped ORM tables not present in canonical schema: "
        f"{unexpected_mapped_tables}"
    )

    column_mismatches: dict[str, dict[str, list[str]]] = {}
    for table_name in sorted(mapped_tables):
        ddl_columns = ddl[table_name]
        orm_columns = {column.name for column in mapped_tables[table_name].columns}

        missing_columns = sorted(ddl_columns - orm_columns)
        extra_columns = sorted(orm_columns - ddl_columns)
        if missing_columns or extra_columns:
            column_mismatches[table_name] = {
                "missing_columns": missing_columns,
                "extra_columns": extra_columns,
            }

    assert column_mismatches == {}, (
        "Canonical schema/ORM column mismatches detected: "
        f"{column_mismatches}"
    )
