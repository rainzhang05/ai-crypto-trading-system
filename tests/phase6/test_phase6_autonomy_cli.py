from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "phase6_autonomy.py"


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


def test_import_path_branch_and_main_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    root = str(ROOT)
    monkeypatch.setattr(sys, "path", [entry for entry in sys.path if entry != root])
    runpy.run_path(str(SCRIPT_PATH), run_name="phase6_autonomy_import_missing_root")
    assert root in sys.path

    monkeypatch.setattr(sys, "argv", [str(SCRIPT_PATH), "--help"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")
    assert exc.value.code == 0


def test_helpers_convert_and_parse_and_db_adapter() -> None:
    cli = _load_cli_module("phase6_autonomy_cli_helpers")
    assert cli._convert_named_params("x=:x AND y::int = 1") == "x=%(x)s AND y::int = 1"
    parsed = cli._parse_ts("2026-01-01T00:00:00Z")
    assert parsed.isoformat() == "2026-01-01T00:00:00+00:00"
    with pytest.raises(argparse.ArgumentTypeError, match="timezone"):
        cli._parse_ts("2026-01-01T00:00:00")

    conn = _FakeConnection(rows=[{"a": 1}])
    db = cli.PsycopgPhase6DB(conn)
    assert db.fetch_one("SELECT :a", {"a": 1}) == {"a": 1}
    assert db.fetch_all("SELECT :a, :b", {"a": 1, "b": 2}) == [{"a": 1}]
    db.execute("UPDATE t SET x = :x", {"x": 1})
    assert conn.executed[-1][0] == "UPDATE t SET x = %(x)s"


def test_connection_resolution_and_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = _load_cli_module("phase6_autonomy_cli_conn")
    expected = _FakeConnection()
    seen: dict[str, Any] = {}

    def _connect(*args: Any, **kwargs: Any) -> _FakeConnection:
        seen["args"] = args
        seen["kwargs"] = kwargs
        return expected

    monkeypatch.setattr(cli.psycopg, "connect", _connect)
    args = argparse.Namespace(dsn="postgresql://x", host=None, port=None, dbname=None, user=None, password=None)
    assert cli._resolve_connection(args) is expected
    assert seen["args"] == ("postgresql://x",)

    args2 = argparse.Namespace(dsn=None, host="h", port="1", dbname="d", user="u", password="p")
    cli._resolve_connection(args2)
    assert seen["kwargs"]["host"] == "h"

    args_missing = argparse.Namespace(dsn=None, host=None, port=None, dbname=None, user=None, password=None)
    for key in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "TEST_DB_HOST", "TEST_DB_PORT", "TEST_DB_NAME", "TEST_DB_USER", "TEST_DB_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(SystemExit, match="Missing DB connection args"):
        cli._resolve_connection(args_missing)

    parser = cli._build_parser()
    parsed = parser.parse_args(["--dsn", "postgresql://x", "daemon", "--max-cycles", "1"])
    assert parsed.command == "daemon"
    assert parsed.max_cycles == 1


def test_universe_helpers_and_build_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = _load_cli_module("phase6_autonomy_cli_universe")
    db = SimpleNamespace(
        fetch_all=lambda _sql, _params: [{"asset_id": 1, "base_asset": "btc"}, {"asset_id": 2, "base_asset": "ETH"}],
    )
    asset_ids = cli._load_asset_ids(db)
    assert asset_ids == {"BTC": 1, "ETH": 2}

    monkeypatch.setattr(cli, "load_universe_symbols", lambda _db, _v: ("BTC",))
    symbols = cli._ensure_universe_state(SimpleNamespace(), SimpleNamespace(), "v1")
    assert symbols == ("BTC",)

    called: dict[str, bool] = {"persist": False}
    monkeypatch.setattr(cli, "load_universe_symbols", lambda _db, _v: ())
    monkeypatch.setattr(cli, "resolve_universe_rows", lambda _r, _k: (SimpleNamespace(symbol="BTC"),))
    monkeypatch.setattr(cli, "persist_universe_version", lambda *_args, **_kwargs: called.__setitem__("persist", True))
    provider = SimpleNamespace(fetch_universe_metadata=lambda: (), fetch_kraken_pairs_and_ohlc=lambda: ())
    symbols2 = cli._ensure_universe_state(SimpleNamespace(), provider, "v1")
    assert symbols2 == ("BTC",)
    assert called["persist"] is True

    cfg = SimpleNamespace(
        hist_market_data_api_key="k",
        hist_market_data_base_url="https://rest.coinapi.io",
        api_budget_per_minute=10,
        kraken_public_base_url="https://api.kraken.com",
        training_universe_version="v1",
    )
    monkeypatch.setattr(cli, "load_phase6_config", lambda: cfg)
    monkeypatch.setattr(cli, "_ensure_universe_state", lambda _db, _provider, _v: ())
    monkeypatch.setattr(
        cli,
        "_load_asset_ids",
        lambda _db: {symbol: idx for idx, symbol in enumerate(cli.UNIVERSE_V1_SYMBOLS, start=1)},
    )
    daemon = cli._build_daemon(argparse.Namespace(), SimpleNamespace())
    assert daemon is not None

    monkeypatch.setattr(cli, "_ensure_universe_state", lambda _db, _provider, _v: ("BTC", "ETH", "XRP"))
    monkeypatch.setattr(cli, "_load_asset_ids", lambda _db: {"BTC": 1, "ETH": 2})
    with pytest.raises(RuntimeError, match="Missing active KRAKEN asset rows"):
        cli._build_daemon(argparse.Namespace(), SimpleNamespace())


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("status", 0),
        ("bootstrap-backfill", 0),
        ("sync-now", 0),
        ("train-now", 0),
        ("repair-gaps", 0),
        ("run-once", 0),
        ("daemon", 0),
    ],
)
def test_main_command_paths(command: str, expected: int, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    cli = _load_cli_module(f"phase6_autonomy_cli_main_{command}")
    conn = _FakeConnection()
    args = argparse.Namespace(
        command=command,
        dsn=None,
        host=None,
        port=None,
        dbname=None,
        user=None,
        password=None,
        max_cycles=1,
        start_ts_utc=None,
        end_ts_utc=None,
    )
    daemon = SimpleNamespace(
        get_status=lambda: SimpleNamespace(
            bootstrap_complete=True,
            universe_symbol_count=30,
            last_ingestion_cycle_id="ic",
            last_training_cycle_id="tc",
            last_training_status="COMPLETED",
        ),
        run_bootstrap_backfill=lambda **_kwargs: None,
        run_incremental_sync=lambda: None,
        run_training=lambda cycle_kind="": None,
        run_gap_repair=lambda: None,
        run_once=lambda: None,
        daemon_loop=lambda max_cycles=None: None,
    )
    monkeypatch.setattr(cli, "_build_parser", lambda: _StubParser(args))
    monkeypatch.setattr(cli, "_resolve_connection", lambda _args: conn)
    monkeypatch.setattr(cli, "_build_daemon", lambda _args, _db: daemon)

    rc = cli.main()
    assert rc == expected
    assert conn.committed is True
    assert conn.closed is True

    if command == "status":
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["bootstrap_complete"] is True


def test_main_unknown_and_exception_rollback(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = _load_cli_module("phase6_autonomy_cli_main_fail")
    conn = _FakeConnection()
    args = argparse.Namespace(command="unknown", dsn=None, host=None, port=None, dbname=None, user=None, password=None, max_cycles=None, start_ts_utc=None, end_ts_utc=None)
    monkeypatch.setattr(cli, "_build_parser", lambda: _StubParser(args))
    monkeypatch.setattr(cli, "_resolve_connection", lambda _args: conn)
    monkeypatch.setattr(cli, "_build_daemon", lambda _args, _db: SimpleNamespace())
    with pytest.raises(SystemExit, match="Unknown command"):
        cli.main()
    assert conn.rolled_back is False
    assert conn.closed is True

    conn2 = _FakeConnection()
    args2 = argparse.Namespace(command="sync-now", dsn=None, host=None, port=None, dbname=None, user=None, password=None, max_cycles=None, start_ts_utc=None, end_ts_utc=None)
    daemon = SimpleNamespace(run_incremental_sync=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(cli, "_build_parser", lambda: _StubParser(args2))
    monkeypatch.setattr(cli, "_resolve_connection", lambda _args: conn2)
    monkeypatch.setattr(cli, "_build_daemon", lambda _args, _db: daemon)
    with pytest.raises(RuntimeError, match="boom"):
        cli.main()
    assert conn2.rolled_back is True
    assert conn2.closed is True
