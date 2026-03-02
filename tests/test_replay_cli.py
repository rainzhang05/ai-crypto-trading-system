"""Unit tests for scripts/replay_cli.py."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "replay_cli.py"


def _load_cli_module(module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class _FakeCursor:
    def __init__(self, conn: "_FakeConnection", row_factory: Any = None) -> None:
        self._conn = conn
        self._row_factory = row_factory

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self._conn.executed.append((sql, params, self._row_factory))

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._conn.fetchall_rows)


class _FakeConnection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.fetchall_rows = rows or []
        self.executed: list[tuple[str, Any, Any]] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self, row_factory: Any = None) -> _FakeCursor:
        return _FakeCursor(self, row_factory=row_factory)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class _StubParser:
    def __init__(self, args: argparse.Namespace) -> None:
        self._args = args

    def parse_args(self) -> argparse.Namespace:
        return self._args


def test_import_path_branch_adds_root_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    root = str(ROOT)
    monkeypatch.setattr(sys, "path", [entry for entry in sys.path if entry != root])
    runpy.run_path(str(SCRIPT_PATH), run_name="replay_cli_import_missing_root")
    assert root in sys.path


def test_import_main_guard_branch_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    root = str(ROOT)
    monkeypatch.setattr(sys, "path", [root, *[entry for entry in sys.path if entry != root]])
    monkeypatch.setattr(sys, "argv", [str(SCRIPT_PATH), "--help"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")
    assert exc.value.code == 0


def test_convert_named_params_and_parse_hour_ts() -> None:
    cli = _load_cli_module("replay_cli_mod_parse")
    assert cli._convert_named_params("x=:x AND y=:y AND z::int=1") == "x=%(x)s AND y=%(y)s AND z::int=1"

    parsed = cli._parse_hour_ts("2026-01-01T12:00:00Z")
    assert parsed.isoformat() == "2026-01-01T12:00:00+00:00"

    with pytest.raises(argparse.ArgumentTypeError, match="Invalid timestamp"):
        cli._parse_hour_ts("not-a-timestamp")
    with pytest.raises(argparse.ArgumentTypeError, match="must include timezone"):
        cli._parse_hour_ts("2026-01-01T12:00:00")


def test_psycopg_runtime_db_adapter_paths() -> None:
    cli = _load_cli_module("replay_cli_mod_db")
    conn = _FakeConnection(rows=[{"value": 1}])
    db = cli.PsycopgRuntimeDB(conn)

    db.begin()
    db.begin()
    assert [call[0] for call in conn.executed].count("BEGIN") == 1

    db.commit()
    db.rollback()
    assert conn.committed is True
    assert conn.rolled_back is True

    row = db.fetch_one("SELECT :value", {"value": 1})
    assert row == {"value": 1}

    conn.fetchall_rows = []
    assert db.fetch_one("SELECT :value", {"value": 1}) is None

    conn.fetchall_rows = [{"a": 1}, {"a": 2}]
    rows = db.fetch_all("SELECT :a, :b", {"a": 1, "b": 2})
    assert rows == [{"a": 1}, {"a": 2}]
    assert conn.executed[-1][0] == "SELECT %(a)s, %(b)s"

    db.execute("UPDATE x SET y = :y WHERE z = :z", {"y": 3, "z": 4})
    assert conn.executed[-1][0] == "UPDATE x SET y = %(y)s WHERE z = %(z)s"


def test_resolve_connection_uses_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = _load_cli_module("replay_cli_mod_conn_dsn")
    expected = _FakeConnection()
    seen: dict[str, Any] = {}

    def _connect(*args: Any, **kwargs: Any) -> _FakeConnection:
        seen["args"] = args
        seen["kwargs"] = kwargs
        return expected

    monkeypatch.setattr(cli.psycopg, "connect", _connect)

    args = argparse.Namespace(
        dsn="postgresql://test",
        host=None,
        port=None,
        dbname=None,
        user=None,
        password=None,
    )
    conn = cli._resolve_connection(args)
    assert conn is expected
    assert seen["args"] == ("postgresql://test",)
    assert seen["kwargs"] == {"autocommit": False}


def test_resolve_connection_from_env_and_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = _load_cli_module("replay_cli_mod_conn_env")
    expected = _FakeConnection()
    seen: dict[str, Any] = {}

    def _connect(*args: Any, **kwargs: Any) -> _FakeConnection:
        seen["args"] = args
        seen["kwargs"] = kwargs
        return expected

    monkeypatch.setattr(cli.psycopg, "connect", _connect)
    monkeypatch.setenv("TEST_DB_HOST", "localhost")
    monkeypatch.setenv("TEST_DB_PORT", "55432")
    monkeypatch.setenv("TEST_DB_NAME", "crypto_db_test")
    monkeypatch.setenv("TEST_DB_USER", "postgres")
    monkeypatch.setenv("TEST_DB_PASSWORD", "postgres")

    args = argparse.Namespace(dsn=None, host=None, port=None, dbname=None, user=None, password=None)
    conn = cli._resolve_connection(args)
    assert conn is expected
    assert seen["args"] == ()
    assert seen["kwargs"]["host"] == "localhost"
    assert seen["kwargs"]["port"] == "55432"
    assert seen["kwargs"]["dbname"] == "crypto_db_test"
    assert seen["kwargs"]["user"] == "postgres"
    assert seen["kwargs"]["password"] == "postgres"
    assert seen["kwargs"]["autocommit"] is False

    for key in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "TEST_DB_HOST", "TEST_DB_PORT", "TEST_DB_NAME", "TEST_DB_USER", "TEST_DB_PASSWORD"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(SystemExit, match="Missing DB connection args"):
        cli._resolve_connection(args)


def test_build_parser_parses_commands() -> None:
    cli = _load_cli_module("replay_cli_mod_parser")
    parser = cli._build_parser()
    parsed = parser.parse_args(
        [
            "--dsn",
            "postgresql://local",
            "execute-hour",
            "--run-id",
            "11111111-1111-4111-8111-111111111111",
            "--account-id",
            "1",
            "--run-mode",
            "LIVE",
            "--hour-ts-utc",
            "2026-01-01T12:00:00Z",
        ]
    )
    assert parsed.command == "execute-hour"
    assert parsed.run_id == UUID("11111111-1111-4111-8111-111111111111")
    assert parsed.account_id == 1
    assert parsed.run_mode == "LIVE"


def test_main_execute_hour_payload_and_close(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    cli = _load_cli_module("replay_cli_mod_main_execute")
    args = argparse.Namespace(
        command="execute-hour",
        run_id=UUID("11111111-1111-4111-8111-111111111111"),
        account_id=1,
        run_mode="LIVE",
        hour_ts_utc=cli._parse_hour_ts("2026-01-01T12:00:00Z"),
    )
    conn = _FakeConnection()
    monkeypatch.setattr(cli, "_build_parser", lambda: _StubParser(args))
    monkeypatch.setattr(cli, "_resolve_connection", lambda _: conn)
    monkeypatch.setattr(
        cli,
        "execute_hour",
        lambda **_: SimpleNamespace(
            trade_signals=[1],
            order_requests=[1, 2],
            order_fills=[1],
            position_lots=[],
            executed_trades=[1],
            risk_events=[1],
            cash_ledger_rows=[1],
            portfolio_hourly_states=[1],
            cluster_exposure_hourly_states=[1],
            risk_hourly_states=[1],
        ),
    )

    assert cli.main() == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["trade_signals"] == 1
    assert payload["order_requests"] == 2
    assert payload["risk_hourly_states"] == 1
    assert conn.closed is True


@pytest.mark.parametrize(("mismatch_count", "expected_code"), [(0, 0), (2, 2)])
def test_main_replay_hour_codes(
    mismatch_count: int,
    expected_code: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = _load_cli_module(f"replay_cli_mod_main_replay_hour_{mismatch_count}")
    args = argparse.Namespace(
        command="replay-hour",
        run_id=UUID("22222222-2222-4222-8222-222222222222"),
        account_id=1,
        hour_ts_utc=cli._parse_hour_ts("2026-01-01T13:00:00Z"),
    )
    conn = _FakeConnection()
    monkeypatch.setattr(cli, "_build_parser", lambda: _StubParser(args))
    monkeypatch.setattr(cli, "_resolve_connection", lambda _: conn)
    monkeypatch.setattr(
        cli,
        "replay_hour",
        lambda **_: SimpleNamespace(
            mismatch_count=mismatch_count,
            mismatches=[
                SimpleNamespace(
                    table_name="trade_signal",
                    key="sig-1",
                    field_name="row_hash",
                    expected="a",
                    actual="b",
                )
            ],
        ),
    )

    assert cli.main() == expected_code
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["mismatch_count"] == mismatch_count
    assert payload["mismatches"][0]["table"] == "trade_signal"
    assert conn.closed is True


@pytest.mark.parametrize(("parity", "expected_code"), [(True, 0), (False, 2)])
def test_main_replay_manifest_codes(
    parity: bool,
    expected_code: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = _load_cli_module(f"replay_cli_mod_main_manifest_{parity}")
    args = argparse.Namespace(
        command="replay-manifest",
        run_id=UUID("33333333-3333-4333-8333-333333333333"),
        account_id=1,
        hour_ts_utc=cli._parse_hour_ts("2026-01-01T14:00:00Z"),
    )
    conn = _FakeConnection()
    monkeypatch.setattr(cli, "_build_parser", lambda: _StubParser(args))
    monkeypatch.setattr(cli, "_resolve_connection", lambda _: conn)
    monkeypatch.setattr(
        cli,
        "replay_manifest_parity",
        lambda **_: SimpleNamespace(
            replay_parity=parity,
            mismatch_count=1 if not parity else 0,
            recomputed_root_hash="a" * 64,
            manifest_root_hash="b" * 64,
            recomputed_authoritative_row_count=10,
            manifest_authoritative_row_count=9,
            failures=[
                SimpleNamespace(
                    failure_code="ROOT_HASH_MISMATCH",
                    severity="CRITICAL",
                    scope="replay_manifest",
                    detail="mismatch",
                    expected="a",
                    actual="b",
                )
            ],
        ),
    )

    assert cli.main() == expected_code
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["replay_parity"] is parity
    assert payload["failures"][0]["code"] == "ROOT_HASH_MISMATCH"
    assert conn.closed is True


def test_main_replay_window_dispatch(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    cli = _load_cli_module("replay_cli_mod_main_window")
    origin = cli._parse_hour_ts("2026-01-01T15:00:00Z")
    args = argparse.Namespace(
        command="replay-window",
        account_id=1,
        run_mode="LIVE",
        start_hour_ts_utc=origin,
        end_hour_ts_utc=origin,
        max_targets=5,
    )
    conn = _FakeConnection()
    monkeypatch.setattr(cli, "_build_parser", lambda: _StubParser(args))
    monkeypatch.setattr(cli, "_resolve_connection", lambda _: conn)
    monkeypatch.setattr(cli, "replay_manifest_tool_parity", lambda **_: pytest.fail("unexpected replay-tool call"))
    monkeypatch.setattr(
        cli,
        "replay_manifest_window_parity",
        lambda **_: SimpleNamespace(
            replay_parity=True,
            total_targets=1,
            passed_targets=1,
            failed_targets=0,
            items=[
                SimpleNamespace(
                    target=SimpleNamespace(
                        run_id=UUID("44444444-4444-4444-8444-444444444444"),
                        account_id=1,
                        run_mode="LIVE",
                        origin_hour_ts_utc=origin,
                    ),
                    report=SimpleNamespace(replay_parity=True, mismatch_count=0, failures=[]),
                )
            ],
        ),
    )

    assert cli.main() == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["total_targets"] == 1
    assert payload["targets"][0]["run_mode"] == "LIVE"
    assert conn.closed is True


def test_main_replay_tool_dispatch_and_exception_close(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = _load_cli_module("replay_cli_mod_main_tool")
    origin = cli._parse_hour_ts("2026-01-01T16:00:00Z")
    args = argparse.Namespace(
        command="replay-tool",
        account_id=None,
        run_mode=None,
        start_hour_ts_utc=None,
        end_hour_ts_utc=None,
        max_targets=None,
    )
    conn = _FakeConnection()
    monkeypatch.setattr(cli, "_build_parser", lambda: _StubParser(args))
    monkeypatch.setattr(cli, "_resolve_connection", lambda _: conn)
    monkeypatch.setattr(cli, "replay_manifest_window_parity", lambda **_: pytest.fail("unexpected replay-window call"))
    monkeypatch.setattr(
        cli,
        "replay_manifest_tool_parity",
        lambda **_: SimpleNamespace(
            replay_parity=False,
            total_targets=1,
            passed_targets=0,
            failed_targets=1,
            items=[
                SimpleNamespace(
                    target=SimpleNamespace(
                        run_id=UUID("55555555-5555-4555-8555-555555555555"),
                        account_id=2,
                        run_mode="PAPER",
                        origin_hour_ts_utc=origin,
                    ),
                    report=SimpleNamespace(
                        replay_parity=False,
                        mismatch_count=1,
                        failures=[SimpleNamespace(failure_code="ROOT_HASH_MISMATCH")],
                    ),
                )
            ],
        ),
    )
    assert cli.main() == 2
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["failed_targets"] == 1
    assert payload["targets"][0]["failure_codes"] == ["ROOT_HASH_MISMATCH"]
    assert conn.closed is True

    error_args = argparse.Namespace(command="execute-hour", run_id=UUID(int=0), account_id=1, run_mode="LIVE", hour_ts_utc=origin)
    conn = _FakeConnection()
    monkeypatch.setattr(cli, "_build_parser", lambda: _StubParser(error_args))
    monkeypatch.setattr(cli, "_resolve_connection", lambda _: conn)
    monkeypatch.setattr(cli, "execute_hour", lambda **_: (_ for _ in ()).throw(RuntimeError("forced cli failure")))
    with pytest.raises(RuntimeError, match="forced cli failure"):
        cli.main()
    assert conn.closed is True
