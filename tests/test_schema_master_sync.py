"""Guards against drift between SCHEMA_DDL_MASTER and canonical bootstrap SQL."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_PATH = ROOT / "schema_bootstrap.sql"
MASTER_PATH = ROOT / "docs/specs/SCHEMA_DDL_MASTER.md"


def _bootstrap_table_names(sql: str) -> set[str]:
    return set(re.findall(r"CREATE TABLE public\.(\w+) \(", sql))


def _master_table_names(markdown: str) -> set[str]:
    return set(re.findall(r"CREATE TABLE\s+(?:public\.)?(\w+)\s*\(", markdown))


def test_schema_master_includes_all_bootstrap_tables() -> None:
    bootstrap_sql = BOOTSTRAP_PATH.read_text(encoding="utf-8")
    master_markdown = MASTER_PATH.read_text(encoding="utf-8")

    bootstrap_tables = _bootstrap_table_names(bootstrap_sql)
    master_tables = _master_table_names(master_markdown)

    missing_from_master = sorted(bootstrap_tables - master_tables)
    assert missing_from_master == [], (
        "SCHEMA_DDL_MASTER.md is missing canonical tables from schema_bootstrap.sql: "
        f"{missing_from_master}"
    )


def test_schema_master_contains_required_phase0_to_phase3_tables() -> None:
    master_markdown = MASTER_PATH.read_text(encoding="utf-8")
    master_tables = _master_table_names(master_markdown)

    required = {
        "run_context",
        "replay_manifest",
        "trade_signal",
        "order_request",
        "risk_event",
        "risk_profile",
        "account_risk_profile_assignment",
    }
    missing_required = sorted(required - master_tables)
    assert missing_required == [], (
        "SCHEMA_DDL_MASTER.md is missing required deterministic core tables: "
        f"{missing_required}"
    )


def test_schema_master_risk_hourly_fk_matches_canonical_identity_linkage() -> None:
    master_markdown = MASTER_PATH.read_text(encoding="utf-8")
    assert "fk_risk_hourly_state_portfolio_identity" in master_markdown, (
        "Expected canonical FK fk_risk_hourly_state_portfolio_identity to be present in "
        "SCHEMA_DDL_MASTER.md."
    )
