"""Authoritative executable-artifact coverage manifest for test policies."""

from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]

# Canonical SQL artifacts that must execute in SQL artifact coverage integration tests.
SQL_EXECUTE_SET: frozenset[str] = frozenset(
    {
        "schema_bootstrap.sql",
        "docs/validations/PHASE_1C_VALIDATION.sql",
        "docs/validations/PHASE_1D_RUNTIME_VALIDATION.sql",
        "docs/validations/PHASE_2_REPLAY_HARNESS_VALIDATION.sql",
        "docs/validations/PHASE_3_RUNTIME_VALIDATION.sql",
        "docs/validations/PHASE_4_ORDER_LIFECYCLE_VALIDATION.sql",
        "docs/validations/PHASE_5_PORTFOLIO_LEDGER_VALIDATION.sql",
        "docs/validations/PHASE_6A_DATA_TRAINING_VALIDATION.sql",
        "docs/validations/PHASE_6B_BACKTEST_ORCHESTRATOR_VALIDATION.sql",
        "docs/validations/TEST_RUNTIME_INSERT_ENABLE.sql",
        "docs/repairs/PHASE_1C_REVISION_C_SCHEMA_REPAIR_BLUEPRINT.sql",
        "docs/repairs/PHASE_1C_REVISION_C_TRIGGER_REPAIR.sql",
    }
)

# Duplicate SQL copies are not executed independently; they must remain equivalent
# to the canonical repair SQL artifacts.
SQL_EQUIVALENCE_PAIRS: tuple[tuple[str, str], ...] = (
    (
        "docs/phases/phase_1_deterministic_contract/PHASE_1C_REVISION_C_SCHEMA_REPAIR_BLUEPRINT.sql",
        "docs/repairs/PHASE_1C_REVISION_C_SCHEMA_REPAIR_BLUEPRINT.sql",
    ),
    (
        "docs/phases/phase_1_deterministic_contract/PHASE_1C_REVISION_C_TRIGGER_REPAIR.sql",
        "docs/repairs/PHASE_1C_REVISION_C_TRIGGER_REPAIR.sql",
    ),
)

# Historical artifact excluded from execution.
SQL_EXCLUDED_SET: frozenset[str] = frozenset({"docs/test_logs/live_schema.sql"})

# Non-SQL executable artifacts that must be contract-validated.
EXECUTABLE_NON_SQL_SET: frozenset[str] = frozenset(
    {
        "scripts/test_all.sh",
        ".github/workflows/ci.yml",
        ".github/workflows/deploy-cloud-run.yml",
        ".github/workflows/release.yml",
        "docker-compose.yml",
        "Makefile",
    }
)


def tracked_executable_artifacts() -> set[str]:
    """Return tracked executable artifact files covered by this policy."""
    tracked_files = set(
        subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    )
    return {
        path
        for path in tracked_files
        if path.endswith((".sql", ".sh", ".yml", ".yaml"))
        or path in {"docker-compose.yml", "Makefile"}
    }


def sql_equivalence_duplicate_set() -> set[str]:
    """Return SQL duplicate files covered by equivalence checks."""
    return {duplicate for duplicate, _canonical in SQL_EQUIVALENCE_PAIRS}


def sql_equivalence_canonical_set() -> set[str]:
    """Return canonical SQL files used by equivalence checks."""
    return {canonical for _duplicate, canonical in SQL_EQUIVALENCE_PAIRS}
