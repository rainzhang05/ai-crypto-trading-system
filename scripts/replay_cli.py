#!/usr/bin/env python3
"""Phase 1D replay CLI for deterministic execution and parity checks."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

# Ensure repository root is importable when script is executed by path.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from execution.replay_engine import execute_hour, replay_hour


_NAMED_PARAM_RE = re.compile(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)")


def _convert_named_params(sql: str) -> str:
    return _NAMED_PARAM_RE.sub(r"%(\1)s", sql)


def _parse_hour_ts(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid timestamp: {value}") from exc
    if ts.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamp must include timezone offset.")
    return ts.astimezone(timezone.utc)


class PsycopgRuntimeDB:
    """Minimal runtime DB adapter implementing execution read/write protocol."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self.conn = conn
        self._tx_started = False

    def begin(self) -> None:
        if self._tx_started:
            return
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
        self._tx_started = True

    def commit(self) -> None:
        self.conn.commit()
        self._tx_started = False

    def rollback(self) -> None:
        self.conn.rollback()
        self._tx_started = False

    def fetch_one(self, sql: str, params: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        rows = self.fetch_all(sql, params)
        return rows[0] if rows else None

    def fetch_all(self, sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        converted = _convert_named_params(sql)
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(converted, dict(params))
            return [dict(row) for row in cur.fetchall()]

    def execute(self, sql: str, params: Mapping[str, Any]) -> None:
        converted = _convert_named_params(sql)
        with self.conn.cursor() as cur:
            cur.execute(converted, dict(params))


def _resolve_connection(args: argparse.Namespace) -> psycopg.Connection[Any]:
    if args.dsn:
        return psycopg.connect(args.dsn, autocommit=False)

    host = args.host or os.getenv("DB_HOST") or os.getenv("TEST_DB_HOST")
    port = args.port or os.getenv("DB_PORT") or os.getenv("TEST_DB_PORT")
    dbname = args.dbname or os.getenv("DB_NAME") or os.getenv("TEST_DB_NAME")
    user = args.user or os.getenv("DB_USER") or os.getenv("TEST_DB_USER")
    password = args.password or os.getenv("DB_PASSWORD") or os.getenv("TEST_DB_PASSWORD")

    missing = [
        key
        for key, value in (
            ("host", host),
            ("port", port),
            ("dbname", dbname),
            ("user", user),
            ("password", password),
        )
        if not value
    ]
    if missing:
        raise SystemExit(
            "Missing DB connection args. Provide --dsn or set --host/--port/--dbname/--user/--password "
            f"(missing: {', '.join(missing)})."
        )

    return psycopg.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        autocommit=False,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic runtime replay CLI")
    parser.add_argument("--dsn", help="PostgreSQL DSN (optional)")
    parser.add_argument("--host", help="DB host")
    parser.add_argument("--port", help="DB port")
    parser.add_argument("--dbname", help="DB name")
    parser.add_argument("--user", help="DB user")
    parser.add_argument("--password", help="DB password")

    subparsers = parser.add_subparsers(dest="command", required=True)

    execute_cmd = subparsers.add_parser("execute-hour", help="Execute deterministic runtime writes")
    execute_cmd.add_argument("--run-id", required=True, type=UUID)
    execute_cmd.add_argument("--account-id", required=True, type=int)
    execute_cmd.add_argument("--run-mode", required=True, choices=("BACKTEST", "PAPER", "LIVE"))
    execute_cmd.add_argument("--hour-ts-utc", required=True, type=_parse_hour_ts)

    replay_cmd = subparsers.add_parser("replay-hour", help="Replay deterministic hour and compare hashes")
    replay_cmd.add_argument("--run-id", required=True, type=UUID)
    replay_cmd.add_argument("--account-id", required=True, type=int)
    replay_cmd.add_argument("--hour-ts-utc", required=True, type=_parse_hour_ts)

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    conn = _resolve_connection(args)
    db = PsycopgRuntimeDB(conn)

    try:
        if args.command == "execute-hour":
            result = execute_hour(
                db=db,
                run_id=args.run_id,
                account_id=args.account_id,
                run_mode=args.run_mode,
                hour_ts_utc=args.hour_ts_utc,
            )
            payload = {
                "trade_signals": len(result.trade_signals),
                "order_requests": len(result.order_requests),
                "risk_events": len(result.risk_events),
            }
            print(json.dumps(payload, sort_keys=True))
            return 0

        report = replay_hour(
            db=db,
            run_id=args.run_id,
            account_id=args.account_id,
            hour_ts_utc=args.hour_ts_utc,
        )
        payload = {
            "mismatch_count": report.mismatch_count,
            "mismatches": [
                {
                    "table": m.table_name,
                    "key": m.key,
                    "field": m.field_name,
                    "expected": m.expected,
                    "actual": m.actual,
                }
                for m in report.mismatches
            ],
        }
        print(json.dumps(payload, sort_keys=True))
        return 0 if report.mismatch_count == 0 else 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
