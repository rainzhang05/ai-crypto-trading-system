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
from execution.decision_engine import normalize_timestamp
from execution.replay_harness import (
    replay_manifest_parity,
    replay_manifest_tool_parity,
    replay_manifest_window_parity,
)


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

    manifest_cmd = subparsers.add_parser(
        "replay-manifest",
        help="Phase 2 replay harness parity check against replay_manifest",
    )
    manifest_cmd.add_argument("--run-id", required=True, type=UUID)
    manifest_cmd.add_argument("--account-id", required=True, type=int)
    manifest_cmd.add_argument("--hour-ts-utc", required=True, type=_parse_hour_ts)

    window_cmd = subparsers.add_parser(
        "replay-window",
        help="Phase 2 replay harness parity check over account/mode hour window",
    )
    window_cmd.add_argument("--account-id", required=True, type=int)
    window_cmd.add_argument("--run-mode", required=True, choices=("BACKTEST", "PAPER", "LIVE"))
    window_cmd.add_argument("--start-hour-ts-utc", required=True, type=_parse_hour_ts)
    window_cmd.add_argument("--end-hour-ts-utc", required=True, type=_parse_hour_ts)
    window_cmd.add_argument("--max-targets", type=int, default=None)

    tool_cmd = subparsers.add_parser(
        "replay-tool",
        help="Deterministic replay tool across discovered run_context targets",
    )
    tool_cmd.add_argument("--account-id", type=int, default=None)
    tool_cmd.add_argument("--run-mode", choices=("BACKTEST", "PAPER", "LIVE"), default=None)
    tool_cmd.add_argument("--start-hour-ts-utc", type=_parse_hour_ts, default=None)
    tool_cmd.add_argument("--end-hour-ts-utc", type=_parse_hour_ts, default=None)
    tool_cmd.add_argument("--max-targets", type=int, default=None)

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
                "order_fills": len(result.order_fills),
                "position_lots": len(result.position_lots),
                "executed_trades": len(result.executed_trades),
                "risk_events": len(result.risk_events),
                "cash_ledger_rows": len(result.cash_ledger_rows),
                "portfolio_hourly_states": len(result.portfolio_hourly_states),
                "cluster_exposure_hourly_states": len(result.cluster_exposure_hourly_states),
                "risk_hourly_states": len(result.risk_hourly_states),
            }
            print(json.dumps(payload, sort_keys=True))
            return 0

        if args.command == "replay-hour":
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

        if args.command == "replay-manifest":
            phase2_report = replay_manifest_parity(
                db=db,
                run_id=args.run_id,
                account_id=args.account_id,
                origin_hour_ts_utc=args.hour_ts_utc,
            )
            payload = {
                "status": "REPLAY PARITY: TRUE" if phase2_report.replay_parity else "REPLAY PARITY: FALSE",
                "replay_parity": phase2_report.replay_parity,
                "mismatch_count": phase2_report.mismatch_count,
                "recomputed_root_hash": phase2_report.recomputed_root_hash,
                "manifest_root_hash": phase2_report.manifest_root_hash,
                "recomputed_authoritative_row_count": phase2_report.recomputed_authoritative_row_count,
                "manifest_authoritative_row_count": phase2_report.manifest_authoritative_row_count,
                "failures": [
                    {
                        "code": failure.failure_code,
                        "severity": failure.severity,
                        "scope": failure.scope,
                        "detail": failure.detail,
                        "expected": failure.expected,
                        "actual": failure.actual,
                    }
                    for failure in phase2_report.failures
                ],
            }
            print(json.dumps(payload, sort_keys=True))
            return 0 if phase2_report.replay_parity else 2

        if args.command == "replay-window":
            window_report = replay_manifest_window_parity(
                db=db,
                account_id=args.account_id,
                run_mode=args.run_mode,
                start_hour_ts_utc=args.start_hour_ts_utc,
                end_hour_ts_utc=args.end_hour_ts_utc,
                max_targets=args.max_targets,
            )
        else:
            window_report = replay_manifest_tool_parity(
                db=db,
                account_id=args.account_id,
                run_mode=args.run_mode,
                start_hour_ts_utc=args.start_hour_ts_utc,
                end_hour_ts_utc=args.end_hour_ts_utc,
                max_targets=args.max_targets,
            )
        payload = {
            "status": "REPLAY PARITY: TRUE" if window_report.replay_parity else "REPLAY PARITY: FALSE",
            "replay_parity": window_report.replay_parity,
            "total_targets": window_report.total_targets,
            "passed_targets": window_report.passed_targets,
            "failed_targets": window_report.failed_targets,
            "targets": [
                {
                    "run_id": str(item.target.run_id),
                    "account_id": item.target.account_id,
                    "run_mode": item.target.run_mode,
                    "origin_hour_ts_utc": normalize_timestamp(item.target.origin_hour_ts_utc),
                    "replay_parity": item.report.replay_parity,
                    "mismatch_count": item.report.mismatch_count,
                    "failure_codes": [failure.failure_code for failure in item.report.failures],
                }
                for item in window_report.items
            ],
        }
        print(json.dumps(payload, sort_keys=True))
        return 0 if window_report.replay_parity else 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
