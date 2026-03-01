"""Unit tests for Phase 2 replay harness architecture primitives."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID

import pytest

from execution.deterministic_context import DeterministicAbortError
from execution.replay_harness import (
    canonical_serialize,
    classify_replay_failure,
    compare_replay_with_manifest,
    discover_replay_targets,
    list_replay_targets,
    load_snapshot_boundary,
    recompute_hash_dag,
    replay_manifest_parity,
    replay_manifest_tool_parity,
    replay_manifest_window_parity,
)


class _FakeReplayDB:
    def __init__(self) -> None:
        self.run_id = UUID("11111111-1111-4111-8111-111111111111")
        self.hour = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        self.rows: dict[str, list[dict[str, Any]]] = {
            "run_context": [
                {
                    "run_id": str(self.run_id),
                    "account_id": 1,
                    "run_mode": "LIVE",
                    "origin_hour_ts_utc": self.hour,
                    "run_seed_hash": "a" * 64,
                    "context_hash": "b" * 64,
                    "replay_root_hash": "c" * 64,
                }
            ],
            "replay_manifest": [
                {
                    "run_seed_hash": "a" * 64,
                    "replay_root_hash": "c" * 64,
                    "authoritative_row_count": 0,
                }
            ],
            "prior_risk": [{"row_hash": "d" * 64}],
            "prior_portfolio": [{"row_hash": "e" * 64}],
            "prior_ledger": [{"ledger_hash": "f" * 64}],
            "model_prediction": [
                {
                    "asset_id": 1,
                    "horizon": "H1",
                    "model_version_id": 9,
                    "hour_ts_utc": self.hour,
                    "row_hash": "1" * 64,
                }
            ],
            "regime_output": [
                {
                    "asset_id": 1,
                    "model_version_id": 9,
                    "hour_ts_utc": self.hour,
                    "row_hash": "2" * 64,
                }
            ],
            "risk_hourly_state": [{"hour_ts_utc": self.hour, "row_hash": "3" * 64}],
            "portfolio_hourly_state": [{"hour_ts_utc": self.hour, "row_hash": "4" * 64}],
            "cluster_exposure_hourly_state": [
                {"cluster_id": 7, "hour_ts_utc": self.hour, "row_hash": "5" * 64}
            ],
            "trade_signal": [{"signal_id": "sig-1", "row_hash": "6" * 64}],
            "order_request": [{"order_id": "ord-1", "row_hash": "7" * 64}],
            "order_fill": [],
            "position_lot": [],
            "executed_trade": [],
            "cash_ledger": [{"ledger_seq": 1, "row_hash": "8" * 64}],
            "risk_event": [{"risk_event_id": "evt-1", "row_hash": "9" * 64}],
        }

    def fetch_one(self, sql: str, params: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        rows = self.fetch_all(sql, params)
        return rows[0] if rows else None

    def fetch_all(self, sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        q = " ".join(sql.lower().split())
        if "from run_context" in q:
            return list(self.rows["run_context"])
        if "from replay_manifest" in q:
            return list(self.rows["replay_manifest"])
        if "from risk_hourly_state" in q and "hour_ts_utc < :origin_hour_ts_utc" in q:
            return list(self.rows["prior_risk"])
        if "from portfolio_hourly_state" in q and "hour_ts_utc < :origin_hour_ts_utc" in q:
            return list(self.rows["prior_portfolio"])
        if "from cash_ledger" in q and "event_ts_utc < :origin_hour_ts_utc" in q:
            return list(self.rows["prior_ledger"])
        if "from model_prediction" in q:
            return list(self.rows["model_prediction"])
        if "from regime_output" in q:
            return list(self.rows["regime_output"])
        if "from risk_hourly_state" in q:
            return list(self.rows["risk_hourly_state"])
        if "from portfolio_hourly_state" in q:
            return list(self.rows["portfolio_hourly_state"])
        if "from cluster_exposure_hourly_state" in q:
            return list(self.rows["cluster_exposure_hourly_state"])
        if "from trade_signal" in q:
            return list(self.rows["trade_signal"])
        if "from order_request" in q:
            return list(self.rows["order_request"])
        if "from order_fill" in q:
            return list(self.rows["order_fill"])
        if "from position_lot" in q:
            return list(self.rows["position_lot"])
        if "from executed_trade" in q:
            return list(self.rows["executed_trade"])
        if "from cash_ledger" in q:
            return list(self.rows["cash_ledger"])
        if "from risk_event" in q:
            return list(self.rows["risk_event"])
        raise RuntimeError(f"Unhandled query: {sql} | params={params}")


def test_canonical_serialize_is_deterministic_and_normalized() -> None:
    ts = datetime(2026, 1, 1, 12, 34, 56, tzinfo=timezone.utc)
    marker_uuid = UUID("22222222-2222-4222-8222-222222222222")
    payload_a = {"b": Decimal("1.200000000000000000"), "a": [ts, True, None, 7], "u": marker_uuid, "f": 1.5}
    payload_b = {"a": [ts, True, None, 7], "b": Decimal("1.2"), "u": marker_uuid, "f": 1.5}

    assert canonical_serialize(payload_a) == canonical_serialize(payload_b)
    assert canonical_serialize({"ts": ts}).endswith('Z"}')


def test_load_snapshot_boundary_missing_run_context_aborts() -> None:
    db = _FakeReplayDB()
    db.rows["run_context"] = []

    with pytest.raises(DeterministicAbortError, match="run_context not found for replay boundary key"):
        load_snapshot_boundary(db, db.run_id, 1, db.hour)


def test_recompute_hash_dag_and_compare_manifest_success() -> None:
    db = _FakeReplayDB()
    boundary = load_snapshot_boundary(db, db.run_id, 1, db.hour)
    recomputed = recompute_hash_dag(db, boundary)

    # Align stored surface to recomputed deterministic values.
    db.rows["run_context"][0]["replay_root_hash"] = recomputed.root_hash
    db.rows["replay_manifest"][0]["replay_root_hash"] = recomputed.root_hash
    db.rows["replay_manifest"][0]["authoritative_row_count"] = recomputed.authoritative_row_count

    report = replay_manifest_parity(db, db.run_id, 1, db.hour)
    assert report.replay_parity is True
    assert report.mismatch_count == 0
    assert report.recomputed_root_hash == recomputed.root_hash
    assert report.recomputed_authoritative_row_count == recomputed.authoritative_row_count


def test_compare_replay_with_manifest_reports_missing_manifest() -> None:
    db = _FakeReplayDB()
    db.rows["replay_manifest"] = []

    boundary = load_snapshot_boundary(db, db.run_id, 1, db.hour)
    recomputed = recompute_hash_dag(db, boundary)
    report = compare_replay_with_manifest(boundary, recomputed)

    codes = {failure.failure_code for failure in report.failures}
    assert report.replay_parity is False
    assert "MANIFEST_MISSING" in codes


def test_replay_manifest_parity_classifies_seed_root_and_count_mismatches() -> None:
    db = _FakeReplayDB()
    db.rows["run_context"][0]["replay_root_hash"] = "f" * 64
    db.rows["replay_manifest"][0]["run_seed_hash"] = "e" * 64
    db.rows["replay_manifest"][0]["replay_root_hash"] = "d" * 64
    db.rows["replay_manifest"][0]["authoritative_row_count"] = 999

    report = replay_manifest_parity(db, db.run_id, 1, db.hour)
    codes = {failure.failure_code for failure in report.failures}

    assert report.replay_parity is False
    assert "RUN_SEED_MISMATCH" in codes
    assert "ROOT_HASH_MISMATCH" in codes
    assert "ROW_COUNT_MISMATCH" in codes
    assert "RUN_CONTEXT_ROOT_MISMATCH" in codes


def test_classify_replay_failure_fallback_and_mapped_severity() -> None:
    mapped = classify_replay_failure("ROOT_HASH_MISMATCH", "root mismatch")
    assert mapped.severity == "CRITICAL"
    assert mapped.scope == "replay_manifest"

    fallback = classify_replay_failure("UNKNOWN_CODE", "unknown mismatch")
    assert fallback.severity == "MEDIUM"
    assert fallback.scope == "unknown"


class _WindowReplayDB:
    def __init__(self) -> None:
        self.hour_1 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        self.hour_2 = datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc)
        self.run_id_1 = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        self.run_id_2 = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

        self.run_context_rows: list[dict[str, Any]] = [
            {
                "run_id": str(self.run_id_1),
                "account_id": 1,
                "run_mode": "LIVE",
                "origin_hour_ts_utc": self.hour_1,
                "run_seed_hash": "a" * 64,
                "context_hash": "b" * 64,
                "replay_root_hash": "0" * 64,
            },
            {
                "run_id": str(self.run_id_2),
                "account_id": 1,
                "run_mode": "LIVE",
                "origin_hour_ts_utc": self.hour_2,
                "run_seed_hash": "c" * 64,
                "context_hash": "d" * 64,
                "replay_root_hash": "0" * 64,
            },
        ]
        self.manifest_rows: list[dict[str, Any]] = [
            {
                "run_id": str(self.run_id_1),
                "account_id": 1,
                "origin_hour_ts_utc": self.hour_1,
                "run_seed_hash": "a" * 64,
                "replay_root_hash": "0" * 64,
                "authoritative_row_count": 0,
            },
            {
                "run_id": str(self.run_id_2),
                "account_id": 1,
                "origin_hour_ts_utc": self.hour_2,
                "run_seed_hash": "c" * 64,
                "replay_root_hash": "0" * 64,
                "authoritative_row_count": 0,
            },
        ]
        self.prior_risk = [{"row_hash": "e" * 64}]
        self.prior_portfolio = [{"row_hash": "f" * 64}]
        self.prior_ledger = [{"ledger_hash": "1" * 64}]

        self.rows_by_run: dict[str, dict[str, list[dict[str, Any]]]] = {
            str(self.run_id_1): {
                "model_prediction": [
                    {
                        "asset_id": 1,
                        "horizon": "H1",
                        "model_version_id": 9,
                        "hour_ts_utc": self.hour_1,
                        "row_hash": "2" * 64,
                    }
                ],
                "regime_output": [
                    {
                        "asset_id": 1,
                        "model_version_id": 9,
                        "hour_ts_utc": self.hour_1,
                        "row_hash": "3" * 64,
                    }
                ],
                "risk_hourly_state": [{"hour_ts_utc": self.hour_1, "row_hash": "4" * 64}],
                "portfolio_hourly_state": [{"hour_ts_utc": self.hour_1, "row_hash": "5" * 64}],
                "cluster_exposure_hourly_state": [
                    {"cluster_id": 7, "hour_ts_utc": self.hour_1, "row_hash": "6" * 64}
                ],
                "trade_signal": [{"signal_id": "sig-1", "row_hash": "7" * 64}],
                "order_request": [{"order_id": "ord-1", "row_hash": "8" * 64}],
                "order_fill": [],
                "position_lot": [],
                "executed_trade": [],
                "cash_ledger": [{"ledger_seq": 1, "row_hash": "9" * 64}],
                "risk_event": [{"risk_event_id": "evt-1", "row_hash": "a" * 64}],
            },
            str(self.run_id_2): {
                "model_prediction": [
                    {
                        "asset_id": 2,
                        "horizon": "H1",
                        "model_version_id": 9,
                        "hour_ts_utc": self.hour_2,
                        "row_hash": "b" * 64,
                    }
                ],
                "regime_output": [
                    {
                        "asset_id": 2,
                        "model_version_id": 9,
                        "hour_ts_utc": self.hour_2,
                        "row_hash": "c" * 64,
                    }
                ],
                "risk_hourly_state": [{"hour_ts_utc": self.hour_2, "row_hash": "d" * 64}],
                "portfolio_hourly_state": [{"hour_ts_utc": self.hour_2, "row_hash": "e" * 64}],
                "cluster_exposure_hourly_state": [
                    {"cluster_id": 8, "hour_ts_utc": self.hour_2, "row_hash": "f" * 64}
                ],
                "trade_signal": [{"signal_id": "sig-2", "row_hash": "1" * 64}],
                "order_request": [{"order_id": "ord-2", "row_hash": "2" * 64}],
                "order_fill": [],
                "position_lot": [],
                "executed_trade": [],
                "cash_ledger": [{"ledger_seq": 1, "row_hash": "3" * 64}],
                "risk_event": [{"risk_event_id": "evt-2", "row_hash": "4" * 64}],
            },
        }

    def fetch_one(self, sql: str, params: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        rows = self.fetch_all(sql, params)
        return rows[0] if rows else None

    def fetch_all(self, sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        q = " ".join(sql.lower().split())
        if "from run_context" in q and "where 1 = 1" in q:
            results: list[dict[str, Any]] = []
            for row in self.run_context_rows:
                if "account_id" in params and int(row["account_id"]) != int(params["account_id"]):
                    continue
                if "run_mode" in params and str(row["run_mode"]) != str(params["run_mode"]):
                    continue
                if (
                    "start_hour_ts_utc" in params
                    and row["origin_hour_ts_utc"] < params["start_hour_ts_utc"]
                ):
                    continue
                if "end_hour_ts_utc" in params and row["origin_hour_ts_utc"] > params["end_hour_ts_utc"]:
                    continue
                results.append(dict(row))
            return results
        if "from run_context" in q and "origin_hour_ts_utc >=" in q:
            results: list[dict[str, Any]] = []
            for row in self.run_context_rows:
                if int(row["account_id"]) != int(params["account_id"]):
                    continue
                if str(row["run_mode"]) != str(params["run_mode"]):
                    continue
                if row["origin_hour_ts_utc"] < params["start_hour_ts_utc"]:
                    continue
                if row["origin_hour_ts_utc"] > params["end_hour_ts_utc"]:
                    continue
                results.append(dict(row))
            return results
        if "from run_context" in q:
            return [
                dict(row)
                for row in self.run_context_rows
                if str(row["run_id"]) == str(params["run_id"])
                and int(row["account_id"]) == int(params["account_id"])
                and row["origin_hour_ts_utc"] == params["origin_hour_ts_utc"]
            ]
        if "from replay_manifest" in q:
            return [
                {
                    "run_seed_hash": row["run_seed_hash"],
                    "replay_root_hash": row["replay_root_hash"],
                    "authoritative_row_count": row["authoritative_row_count"],
                }
                for row in self.manifest_rows
                if str(row["run_id"]) == str(params["run_id"])
                and int(row["account_id"]) == int(params["account_id"])
                and row["origin_hour_ts_utc"] == params["origin_hour_ts_utc"]
            ]

        if "from risk_hourly_state" in q and "hour_ts_utc < :origin_hour_ts_utc" in q:
            return list(self.prior_risk)
        if "from portfolio_hourly_state" in q and "hour_ts_utc < :origin_hour_ts_utc" in q:
            return list(self.prior_portfolio)
        if "from cash_ledger" in q and "event_ts_utc < :origin_hour_ts_utc" in q:
            return list(self.prior_ledger)

        run_rows = self.rows_by_run[str(params["run_id"])]
        if "from model_prediction" in q:
            return list(run_rows["model_prediction"])
        if "from regime_output" in q:
            return list(run_rows["regime_output"])
        if "from risk_hourly_state" in q:
            return list(run_rows["risk_hourly_state"])
        if "from portfolio_hourly_state" in q:
            return list(run_rows["portfolio_hourly_state"])
        if "from cluster_exposure_hourly_state" in q:
            return list(run_rows["cluster_exposure_hourly_state"])
        if "from trade_signal" in q:
            return list(run_rows["trade_signal"])
        if "from order_request" in q:
            return list(run_rows["order_request"])
        if "from order_fill" in q:
            return list(run_rows["order_fill"])
        if "from position_lot" in q:
            return list(run_rows["position_lot"])
        if "from executed_trade" in q:
            return list(run_rows["executed_trade"])
        if "from cash_ledger" in q:
            return list(run_rows["cash_ledger"])
        if "from risk_event" in q:
            return list(run_rows["risk_event"])
        raise RuntimeError(f"Unhandled query: {sql} | params={params}")


def _align_window_db_roots(db: _WindowReplayDB) -> None:
    for run_context in db.run_context_rows:
        boundary = load_snapshot_boundary(
            db=db,
            run_id=UUID(str(run_context["run_id"])),
            account_id=int(run_context["account_id"]),
            origin_hour_ts_utc=run_context["origin_hour_ts_utc"],
        )
        recomputed = recompute_hash_dag(db=db, boundary=boundary)
        run_context["replay_root_hash"] = recomputed.root_hash
        for row in db.manifest_rows:
            if (
                str(row["run_id"]) == str(run_context["run_id"])
                and row["origin_hour_ts_utc"] == run_context["origin_hour_ts_utc"]
            ):
                row["replay_root_hash"] = recomputed.root_hash
                row["authoritative_row_count"] = recomputed.authoritative_row_count


def test_list_replay_targets_success_and_max_targets() -> None:
    db = _WindowReplayDB()
    targets = list_replay_targets(db, 1, "LIVE", db.hour_1, db.hour_2)
    assert len(targets) == 2
    assert targets[0].run_id == db.run_id_1
    clipped = list_replay_targets(db, 1, "LIVE", db.hour_1, db.hour_2, max_targets=1)
    assert len(clipped) == 1
    assert clipped[0].run_id == db.run_id_1


def test_list_replay_targets_invalid_inputs_abort() -> None:
    db = _WindowReplayDB()
    with pytest.raises(DeterministicAbortError, match="end_hour_ts_utc must be >= start_hour_ts_utc"):
        list_replay_targets(db, 1, "LIVE", db.hour_2, db.hour_1)
    with pytest.raises(DeterministicAbortError, match="max_targets must be > 0"):
        list_replay_targets(db, 1, "LIVE", db.hour_1, db.hour_2, max_targets=0)


def test_list_replay_targets_no_rows_abort() -> None:
    db = _WindowReplayDB()
    with pytest.raises(DeterministicAbortError, match="No run_context rows found for replay target window"):
        list_replay_targets(
            db,
            1,
            "LIVE",
            datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 2, 1, 0, tzinfo=timezone.utc),
        )


def test_replay_manifest_window_parity_reports_mixed_results() -> None:
    db = _WindowReplayDB()
    _align_window_db_roots(db)
    # Introduce a deterministic manifest mismatch on the second target.
    db.manifest_rows[1]["replay_root_hash"] = "9" * 64

    report = replay_manifest_window_parity(
        db=db,
        account_id=1,
        run_mode="LIVE",
        start_hour_ts_utc=db.hour_1,
        end_hour_ts_utc=db.hour_2,
    )
    assert report.replay_parity is False
    assert report.total_targets == 2
    assert report.passed_targets == 1
    assert report.failed_targets == 1
    assert report.items[0].target.run_id == db.run_id_1
    assert report.items[0].report.replay_parity is True
    assert report.items[1].target.run_id == db.run_id_2
    assert report.items[1].report.replay_parity is False


def test_discover_replay_targets_with_filters_and_empty_result() -> None:
    db = _WindowReplayDB()
    all_targets = discover_replay_targets(db)
    assert len(all_targets) == 2
    clipped = discover_replay_targets(db, max_targets=1)
    assert len(clipped) == 1
    assert clipped[0].run_id == db.run_id_1

    scoped = discover_replay_targets(
        db,
        account_id=1,
        run_mode="LIVE",
        start_hour_ts_utc=db.hour_2,
        end_hour_ts_utc=db.hour_2,
    )
    assert len(scoped) == 1
    assert scoped[0].run_id == db.run_id_2

    no_targets = discover_replay_targets(
        db,
        account_id=1,
        run_mode="LIVE",
        start_hour_ts_utc=datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc),
        end_hour_ts_utc=datetime(2026, 1, 2, 1, 0, tzinfo=timezone.utc),
    )
    assert no_targets == tuple()


def test_discover_replay_targets_invalid_bounds_or_limit_abort() -> None:
    db = _WindowReplayDB()
    with pytest.raises(DeterministicAbortError, match="end_hour_ts_utc must be >= start_hour_ts_utc"):
        discover_replay_targets(db, start_hour_ts_utc=db.hour_2, end_hour_ts_utc=db.hour_1)
    with pytest.raises(DeterministicAbortError, match="max_targets must be > 0"):
        discover_replay_targets(db, max_targets=0)


def test_replay_manifest_tool_parity_empty_targets_returns_true() -> None:
    db = _WindowReplayDB()
    report = replay_manifest_tool_parity(
        db=db,
        account_id=1,
        run_mode="LIVE",
        start_hour_ts_utc=datetime(2026, 1, 3, 0, 0, tzinfo=timezone.utc),
        end_hour_ts_utc=datetime(2026, 1, 3, 1, 0, tzinfo=timezone.utc),
    )
    assert report.replay_parity is True
    assert report.total_targets == 0
    assert report.items == tuple()


def test_replay_manifest_tool_parity_reports_mixed_results() -> None:
    db = _WindowReplayDB()
    _align_window_db_roots(db)
    db.manifest_rows[1]["replay_root_hash"] = "8" * 64

    report = replay_manifest_tool_parity(db=db, run_mode="LIVE")
    assert report.replay_parity is False
    assert report.total_targets == 2
    assert report.passed_targets == 1
    assert report.failed_targets == 1
