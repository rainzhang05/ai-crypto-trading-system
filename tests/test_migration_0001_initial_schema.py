"""Unit tests for initial Alembic migration orchestration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
from typing import Any

import pytest


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "db"
    / "migrations"
    / "versions"
    / "0001_initial_schema.py"
)


class _OpStub:
    def __init__(self, *, fail_on: str | None = None) -> None:
        self.calls: list[str] = []
        self.fail_on = fail_on

    def execute(self, statement: str) -> None:
        self.calls.append(statement)
        if self.fail_on and self.fail_on in statement:
            raise RuntimeError("forced migration failure")


def _load_migration_module(module_name: str, op_stub: _OpStub, monkeypatch: pytest.MonkeyPatch) -> Any:
    fake_alembic = types.ModuleType("alembic")
    fake_alembic.op = op_stub
    monkeypatch.setitem(sys.modules, "alembic", fake_alembic)

    spec = importlib.util.spec_from_file_location(module_name, MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_revision_metadata_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_migration_module("migration_0001_meta", _OpStub(), monkeypatch)
    assert module.revision == "0001_initial_schema"
    assert module.down_revision is None
    assert module.branch_labels is None
    assert module.depends_on is None


def test_execute_all_runs_all_statements_and_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    op_stub = _OpStub()
    module = _load_migration_module("migration_0001_execute", op_stub, monkeypatch)

    module._execute_all(("SELECT 1;", "SELECT 2;"))
    assert op_stub.calls == ["SELECT 1;", "SELECT 2;"]

    op_stub.calls.clear()
    module._execute_all(())
    assert op_stub.calls == []


def test_execute_all_logs_and_reraises(monkeypatch: pytest.MonkeyPatch) -> None:
    op_stub = _OpStub(fail_on="SELECT 2")
    module = _load_migration_module("migration_0001_execute_error", op_stub, monkeypatch)

    seen: list[str] = []
    monkeypatch.setattr(module.logger, "exception", lambda message: seen.append(message))
    with pytest.raises(RuntimeError, match="forced migration failure"):
        module._execute_all(("SELECT 1;", "SELECT 2;"))

    assert seen == ["Migration statement failed."]


def test_upgrade_orchestration_order(monkeypatch: pytest.MonkeyPatch) -> None:
    op_stub = _OpStub()
    module = _load_migration_module("migration_0001_upgrade", op_stub, monkeypatch)

    groups: list[tuple[str, ...]] = []
    monkeypatch.setattr(module, "_execute_all", lambda statements: groups.append(tuple(statements)))
    module.upgrade()

    assert op_stub.calls[0] == "CREATE EXTENSION IF NOT EXISTS timescaledb;"
    assert groups == [
        module.ENUM_DDL,
        module.TABLE_DDL,
        module.INDEX_DDL,
        module.TIMESCALE_HYPERTABLE_DDL,
        module.TIMESCALE_COMPRESSION_DDL,
        module.APPEND_ONLY_DDL,
    ]


def test_downgrade_orchestration_drop_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_migration_module("migration_0001_downgrade", _OpStub(), monkeypatch)

    statements_seen: list[tuple[str, ...]] = []
    monkeypatch.setattr(module, "_execute_all", lambda statements: statements_seen.append(tuple(statements)))
    module.downgrade()

    assert len(statements_seen) == 1
    drops = statements_seen[0]
    assert drops[0].startswith("DROP TRIGGER IF EXISTS trg_backtest_fold_result_append_only")
    assert "SELECT remove_compression_policy('cash_ledger', if_exists => TRUE);" in drops
    assert drops[-1] == "DROP TYPE IF EXISTS run_mode_enum;"
