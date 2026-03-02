#!/usr/bin/env python3
"""Phase 6 autonomous data/training orchestration CLI."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Optional, Sequence

import psycopg
from psycopg.rows import dict_row

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from execution.phase6.autonomy_daemon import Phase6AutonomyDaemon
from execution.phase6.coinapi_provider import CoinApiProvider
from execution.phase6.kraken_public_provider import KrakenPublicProvider
from execution.phase6.phase6_config import load_phase6_config
from execution.phase6.provider_stack import Phase6ProviderStack
from execution.phase6.universe_manager import (
    UNIVERSE_V1_SYMBOLS,
    load_universe_symbols,
    persist_universe_version,
    resolve_universe_rows,
)


_NAMED_PARAM_RE = re.compile(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)")


def _convert_named_params(sql: str) -> str:
    return _NAMED_PARAM_RE.sub(r"%(\1)s", sql)


def _parse_ts(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    ts = datetime.fromisoformat(normalized)
    if ts.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamp must include timezone offset.")
    return ts.astimezone(timezone.utc)


class PsycopgPhase6DB:
    """Minimal DB adapter for Phase 6 modules."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self.conn = conn

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
        for key, value in (("host", host), ("port", port), ("dbname", dbname), ("user", user), ("password", password))
        if not value
    ]
    if missing:
        raise SystemExit(
            "Missing DB connection args. Provide --dsn or set --host/--port/--dbname/--user/--password "
            f"(missing: {', '.join(missing)})."
        )

    return psycopg.connect(host=host, port=port, dbname=dbname, user=user, password=password, autocommit=False)


def _load_asset_ids(db: PsycopgPhase6DB) -> dict[str, int]:
    rows = db.fetch_all(
        """
        SELECT asset_id, base_asset
        FROM asset
        WHERE venue = 'KRAKEN'
          AND is_active = TRUE
        """,
        {},
    )
    return {str(row["base_asset"]).upper(): int(row["asset_id"]) for row in rows}


def _ensure_universe_state(db: PsycopgPhase6DB, provider: Phase6ProviderStack, version_code: str) -> tuple[str, ...]:
    symbols = load_universe_symbols(db, version_code)
    if symbols:
        return symbols

    ranking_rows = provider.fetch_universe_metadata()
    kraken_rows = provider.fetch_kraken_pairs_and_ohlc()
    resolved = resolve_universe_rows(ranking_rows, kraken_rows)
    persist_universe_version(
        db,
        version_code=version_code,
        generated_at_utc=datetime.now(tz=timezone.utc),
        rows=resolved,
        source_policy="COINAPI+KRAKEN_PUBLIC",
    )
    return tuple(row.symbol for row in resolved)


def _build_daemon(args: argparse.Namespace, db: PsycopgPhase6DB) -> Phase6AutonomyDaemon:
    cfg = load_phase6_config()
    coinapi = CoinApiProvider(
        api_key=cfg.hist_market_data_api_key,
        base_url=cfg.hist_market_data_base_url,
        request_budget_per_minute=cfg.api_budget_per_minute,
    )
    kraken = KrakenPublicProvider(base_url=cfg.kraken_public_base_url)
    provider = Phase6ProviderStack(coinapi=coinapi, kraken_public=kraken)

    symbols = _ensure_universe_state(db, provider, cfg.training_universe_version)
    if not symbols:
        symbols = UNIVERSE_V1_SYMBOLS

    asset_ids = _load_asset_ids(db)
    missing = [symbol for symbol in symbols if symbol not in asset_ids]
    if missing:
        raise RuntimeError(f"Missing active KRAKEN asset rows for symbols: {missing}")

    return Phase6AutonomyDaemon(
        db=db,
        provider=provider,
        config=cfg,
        symbols=symbols,
        asset_id_by_symbol=asset_ids,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 6 autonomous data/training CLI")
    parser.add_argument("--dsn", help="PostgreSQL DSN (optional)")
    parser.add_argument("--host", help="DB host")
    parser.add_argument("--port", help="DB port")
    parser.add_argument("--dbname", help="DB name")
    parser.add_argument("--user", help="DB user")
    parser.add_argument("--password", help="DB password")

    subparsers = parser.add_subparsers(dest="command", required=True)

    daemon_cmd = subparsers.add_parser("daemon", help="Start autonomy daemon loop")
    daemon_cmd.add_argument("--max-cycles", type=int, default=None)

    subparsers.add_parser("run-once", help="Run one full daemon iteration")

    bootstrap = subparsers.add_parser("bootstrap-backfill", help="Run strict bootstrap backfill")
    bootstrap.add_argument("--start-ts-utc", type=_parse_ts, default=None)
    bootstrap.add_argument("--end-ts-utc", type=_parse_ts, default=None)

    subparsers.add_parser("sync-now", help="Run incremental sync cycle")
    subparsers.add_parser("train-now", help="Run scheduled training cycle")
    subparsers.add_parser("repair-gaps", help="Run gap repair cycle")
    subparsers.add_parser("status", help="Get daemon status")

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    conn = _resolve_connection(args)
    db = PsycopgPhase6DB(conn)
    try:
        daemon = _build_daemon(args, db)

        if args.command == "status":
            status = daemon.get_status()
            print(
                json.dumps(
                    {
                        "bootstrap_complete": status.bootstrap_complete,
                        "universe_symbol_count": status.universe_symbol_count,
                        "last_ingestion_cycle_id": status.last_ingestion_cycle_id,
                        "last_training_cycle_id": status.last_training_cycle_id,
                        "last_training_status": status.last_training_status,
                    },
                    sort_keys=True,
                )
            )
            conn.commit()
            return 0

        if args.command == "bootstrap-backfill":
            end_ts = args.end_ts_utc or datetime.now(tz=timezone.utc)
            start_ts = args.start_ts_utc or (end_ts - timedelta(days=365 * 5))
            daemon.run_bootstrap_backfill(start_ts_utc=start_ts, end_ts_utc=end_ts)
            conn.commit()
            return 0

        if args.command == "sync-now":
            daemon.run_incremental_sync()
            conn.commit()
            return 0

        if args.command == "train-now":
            daemon.run_training(cycle_kind="MANUAL")
            conn.commit()
            return 0

        if args.command == "repair-gaps":
            daemon.run_gap_repair()
            conn.commit()
            return 0

        if args.command == "run-once":
            daemon.run_once()
            conn.commit()
            return 0

        if args.command == "daemon":
            daemon.daemon_loop(max_cycles=args.max_cycles)
            conn.commit()
            return 0

        raise SystemExit(f"Unknown command: {args.command}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
