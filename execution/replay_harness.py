"""Phase 2 replay harness primitives and parity comparison engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
from typing import Any, Mapping, Optional, Protocol, Sequence
from uuid import UUID

from execution.decision_engine import normalize_timestamp, normalize_token, stable_hash
from execution.deterministic_context import DeterministicAbortError


class ReplayHarnessDatabase(Protocol):
    """Read-only DB contract used by replay harness components."""

    def fetch_one(self, sql: str, params: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        """Fetch one row."""

    def fetch_all(self, sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        """Fetch many rows."""


@dataclass(frozen=True)
class ReplayManifestState:
    run_seed_hash: str
    replay_root_hash: str
    authoritative_row_count: int


@dataclass(frozen=True)
class ReplaySnapshotBoundary:
    run_id: UUID
    account_id: int
    run_mode: str
    origin_hour_ts_utc: datetime
    run_seed_hash: str
    context_hash: str
    run_context_replay_root_hash: str
    prior_risk_state_hash: Optional[str]
    prior_portfolio_state_hash: Optional[str]
    prior_ledger_hash: Optional[str]
    manifest: Optional[ReplayManifestState]


@dataclass(frozen=True)
class ReplayTableDigest:
    table_name: str
    row_count: int
    rowset_digest: str


@dataclass(frozen=True)
class ReplayHashNode:
    node_name: str
    node_hash: str
    parent_hashes: tuple[str, ...]


@dataclass(frozen=True)
class ReplayDagResult:
    boundary_hash: str
    root_hash: str
    authoritative_row_count: int
    table_digests: tuple[ReplayTableDigest, ...]
    hash_nodes: tuple[ReplayHashNode, ...]


@dataclass(frozen=True)
class ReplayFailure:
    failure_code: str
    severity: str
    scope: str
    detail: str
    expected: Optional[str]
    actual: Optional[str]


@dataclass(frozen=True)
class ReplayComparisonReport:
    replay_parity: bool
    mismatch_count: int
    failures: tuple[ReplayFailure, ...]
    recomputed_root_hash: str
    manifest_root_hash: Optional[str]
    recomputed_authoritative_row_count: int
    manifest_authoritative_row_count: Optional[int]


@dataclass(frozen=True)
class ReplayTarget:
    run_id: UUID
    account_id: int
    run_mode: str
    origin_hour_ts_utc: datetime


@dataclass(frozen=True)
class ReplayWindowItem:
    target: ReplayTarget
    report: ReplayComparisonReport


@dataclass(frozen=True)
class ReplayWindowReport:
    replay_parity: bool
    total_targets: int
    passed_targets: int
    failed_targets: int
    items: tuple[ReplayWindowItem, ...]


@dataclass(frozen=True)
class _ReplayTableSpec:
    table_name: str
    key_columns: tuple[str, ...]
    hash_column: str
    sql: str


_REPLAY_TABLE_SPECS: tuple[_ReplayTableSpec, ...] = (
    _ReplayTableSpec(
        table_name="model_prediction",
        key_columns=("asset_id", "horizon", "model_version_id", "hour_ts_utc"),
        hash_column="row_hash",
        sql="""
        SELECT asset_id, horizon, model_version_id, hour_ts_utc, row_hash
        FROM model_prediction
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND hour_ts_utc = :origin_hour_ts_utc
        ORDER BY asset_id ASC, horizon ASC, model_version_id ASC, row_hash ASC
        """,
    ),
    _ReplayTableSpec(
        table_name="regime_output",
        key_columns=("asset_id", "model_version_id", "hour_ts_utc"),
        hash_column="row_hash",
        sql="""
        SELECT asset_id, model_version_id, hour_ts_utc, row_hash
        FROM regime_output
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND hour_ts_utc = :origin_hour_ts_utc
        ORDER BY asset_id ASC, model_version_id ASC, row_hash ASC
        """,
    ),
    _ReplayTableSpec(
        table_name="risk_hourly_state",
        key_columns=("hour_ts_utc",),
        hash_column="row_hash",
        sql="""
        SELECT hour_ts_utc, row_hash
        FROM risk_hourly_state
        WHERE source_run_id = :run_id
          AND run_mode = :run_mode
          AND account_id = :account_id
          AND hour_ts_utc = :origin_hour_ts_utc
        ORDER BY hour_ts_utc ASC
        """,
    ),
    _ReplayTableSpec(
        table_name="portfolio_hourly_state",
        key_columns=("hour_ts_utc",),
        hash_column="row_hash",
        sql="""
        SELECT hour_ts_utc, row_hash
        FROM portfolio_hourly_state
        WHERE source_run_id = :run_id
          AND run_mode = :run_mode
          AND account_id = :account_id
          AND hour_ts_utc = :origin_hour_ts_utc
        ORDER BY hour_ts_utc ASC
        """,
    ),
    _ReplayTableSpec(
        table_name="cluster_exposure_hourly_state",
        key_columns=("cluster_id", "hour_ts_utc"),
        hash_column="row_hash",
        sql="""
        SELECT cluster_id, hour_ts_utc, row_hash
        FROM cluster_exposure_hourly_state
        WHERE source_run_id = :run_id
          AND run_mode = :run_mode
          AND account_id = :account_id
          AND hour_ts_utc = :origin_hour_ts_utc
        ORDER BY cluster_id ASC, row_hash ASC
        """,
    ),
    _ReplayTableSpec(
        table_name="trade_signal",
        key_columns=("signal_id",),
        hash_column="row_hash",
        sql="""
        SELECT signal_id, row_hash
        FROM trade_signal
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND hour_ts_utc = :origin_hour_ts_utc
        ORDER BY signal_id ASC
        """,
    ),
    _ReplayTableSpec(
        table_name="order_request",
        key_columns=("order_id",),
        hash_column="row_hash",
        sql="""
        SELECT order_id, row_hash
        FROM order_request
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :origin_hour_ts_utc
        ORDER BY order_id ASC
        """,
    ),
    _ReplayTableSpec(
        table_name="order_fill",
        key_columns=("fill_id",),
        hash_column="row_hash",
        sql="""
        SELECT fill_id, row_hash
        FROM order_fill
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :origin_hour_ts_utc
        ORDER BY fill_id ASC
        """,
    ),
    _ReplayTableSpec(
        table_name="position_lot",
        key_columns=("lot_id",),
        hash_column="row_hash",
        sql="""
        SELECT lot_id, row_hash
        FROM position_lot
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :origin_hour_ts_utc
        ORDER BY lot_id ASC
        """,
    ),
    _ReplayTableSpec(
        table_name="executed_trade",
        key_columns=("trade_id",),
        hash_column="row_hash",
        sql="""
        SELECT trade_id, row_hash
        FROM executed_trade
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :origin_hour_ts_utc
        ORDER BY trade_id ASC
        """,
    ),
    _ReplayTableSpec(
        table_name="cash_ledger",
        key_columns=("ledger_seq",),
        hash_column="row_hash",
        sql="""
        SELECT ledger_seq, row_hash
        FROM cash_ledger
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :origin_hour_ts_utc
        ORDER BY ledger_seq ASC
        """,
    ),
    _ReplayTableSpec(
        table_name="risk_event",
        key_columns=("risk_event_id",),
        hash_column="row_hash",
        sql="""
        SELECT risk_event_id, row_hash
        FROM risk_event
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :origin_hour_ts_utc
        ORDER BY risk_event_id ASC
        """,
    ),
)


_FAILURE_CLASSIFICATION: Mapping[str, tuple[str, str]] = {
    "MANIFEST_MISSING": ("CRITICAL", "replay_manifest"),
    "RUN_SEED_MISMATCH": ("HIGH", "replay_manifest"),
    "ROOT_HASH_MISMATCH": ("CRITICAL", "replay_manifest"),
    "ROW_COUNT_MISMATCH": ("HIGH", "replay_manifest"),
    "RUN_CONTEXT_ROOT_MISMATCH": ("HIGH", "run_context"),
}


def canonical_serialize(payload: Any) -> str:
    """Serialize payload into deterministic canonical JSON."""
    canonical_payload = _canonicalize_value(payload)
    return json.dumps(
        canonical_payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def load_snapshot_boundary(
    db: ReplayHarnessDatabase,
    run_id: UUID,
    account_id: int,
    origin_hour_ts_utc: datetime,
) -> ReplaySnapshotBoundary:
    """Load replay snapshot boundary and associated manifest state."""
    params = {
        "run_id": str(run_id),
        "account_id": account_id,
        "origin_hour_ts_utc": origin_hour_ts_utc,
    }
    run_context = db.fetch_one(
        """
        SELECT run_id, account_id, run_mode, origin_hour_ts_utc,
               run_seed_hash, context_hash, replay_root_hash
        FROM run_context
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :origin_hour_ts_utc
        """,
        params,
    )
    if run_context is None:
        raise DeterministicAbortError("run_context not found for replay boundary key.")

    manifest_row = db.fetch_one(
        """
        SELECT run_seed_hash, replay_root_hash, authoritative_row_count
        FROM replay_manifest
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :origin_hour_ts_utc
        """,
        params,
    )

    mode_params = dict(params)
    mode_params["run_mode"] = str(run_context["run_mode"])
    prior_risk = db.fetch_one(
        """
        SELECT row_hash
        FROM risk_hourly_state
        WHERE run_mode = :run_mode
          AND account_id = :account_id
          AND hour_ts_utc < :origin_hour_ts_utc
        ORDER BY hour_ts_utc DESC
        LIMIT 1
        """,
        mode_params,
    )
    prior_portfolio = db.fetch_one(
        """
        SELECT row_hash
        FROM portfolio_hourly_state
        WHERE run_mode = :run_mode
          AND account_id = :account_id
          AND hour_ts_utc < :origin_hour_ts_utc
        ORDER BY hour_ts_utc DESC
        LIMIT 1
        """,
        mode_params,
    )
    prior_ledger = db.fetch_one(
        """
        SELECT ledger_hash
        FROM cash_ledger
        WHERE run_mode = :run_mode
          AND account_id = :account_id
          AND event_ts_utc < :origin_hour_ts_utc
        ORDER BY event_ts_utc DESC, ledger_seq DESC
        LIMIT 1
        """,
        mode_params,
    )

    manifest = (
        ReplayManifestState(
            run_seed_hash=str(manifest_row["run_seed_hash"]),
            replay_root_hash=str(manifest_row["replay_root_hash"]),
            authoritative_row_count=int(manifest_row["authoritative_row_count"]),
        )
        if manifest_row is not None
        else None
    )
    return ReplaySnapshotBoundary(
        run_id=UUID(str(run_context["run_id"])),
        account_id=int(run_context["account_id"]),
        run_mode=str(run_context["run_mode"]),
        origin_hour_ts_utc=run_context["origin_hour_ts_utc"],
        run_seed_hash=str(run_context["run_seed_hash"]),
        context_hash=str(run_context["context_hash"]),
        run_context_replay_root_hash=str(run_context["replay_root_hash"]),
        prior_risk_state_hash=str(prior_risk["row_hash"]) if prior_risk is not None else None,
        prior_portfolio_state_hash=(
            str(prior_portfolio["row_hash"]) if prior_portfolio is not None else None
        ),
        prior_ledger_hash=str(prior_ledger["ledger_hash"]) if prior_ledger is not None else None,
        manifest=manifest,
    )


def recompute_hash_dag(
    db: ReplayHarnessDatabase,
    boundary: ReplaySnapshotBoundary,
) -> ReplayDagResult:
    """Recompute deterministic replay hash DAG and canonical replay root."""
    boundary_hash = stable_hash(
        (
            "phase_2_boundary_v1",
            boundary.run_seed_hash,
            boundary.context_hash,
            normalize_timestamp(boundary.origin_hour_ts_utc),
            boundary.prior_risk_state_hash or "",
            boundary.prior_portfolio_state_hash or "",
            boundary.prior_ledger_hash or "",
        )
    )

    params = {
        "run_id": str(boundary.run_id),
        "account_id": boundary.account_id,
        "run_mode": boundary.run_mode,
        "origin_hour_ts_utc": boundary.origin_hour_ts_utc,
    }

    digests: list[ReplayTableDigest] = []
    nodes: list[ReplayHashNode] = [ReplayHashNode("boundary", boundary_hash, tuple())]

    run_context_row = {
        "run_id": str(boundary.run_id),
        "account_id": boundary.account_id,
        "run_mode": boundary.run_mode,
        "origin_hour_ts_utc": boundary.origin_hour_ts_utc,
        "context_hash": boundary.context_hash,
    }
    run_context_digest = _compute_table_digest(
        table_name="run_context",
        key_columns=("run_id", "account_id", "run_mode", "origin_hour_ts_utc"),
        hash_column="context_hash",
        rows=(run_context_row,),
        boundary_hash=boundary_hash,
    )
    digests.append(run_context_digest)

    prior_node_hash = stable_hash(
        (
            "phase_2_table_node_v1",
            nodes[-1].node_hash,
            run_context_digest.table_name,
            run_context_digest.rowset_digest,
            str(run_context_digest.row_count),
        )
    )
    nodes.append(
        ReplayHashNode(
            node_name=run_context_digest.table_name,
            node_hash=prior_node_hash,
            parent_hashes=(nodes[0].node_hash,),
        )
    )

    for spec in _REPLAY_TABLE_SPECS:
        rows = db.fetch_all(spec.sql, params)
        digest = _compute_table_digest(
            table_name=spec.table_name,
            key_columns=spec.key_columns,
            hash_column=spec.hash_column,
            rows=rows,
            boundary_hash=boundary_hash,
        )
        digests.append(digest)
        node_hash = stable_hash(
            (
                "phase_2_table_node_v1",
                prior_node_hash,
                digest.table_name,
                digest.rowset_digest,
                str(digest.row_count),
            )
        )
        nodes.append(
            ReplayHashNode(
                node_name=digest.table_name,
                node_hash=node_hash,
                parent_hashes=(prior_node_hash,),
            )
        )
        prior_node_hash = node_hash

    replay_root_hash = stable_hash(
        (
            "phase_2_replay_root_v1",
            boundary_hash,
            *[f"{node.node_name}:{node.node_hash}" for node in nodes[1:]],
        )
    )
    authoritative_row_count = sum(digest.row_count for digest in digests)
    return ReplayDagResult(
        boundary_hash=boundary_hash,
        root_hash=replay_root_hash,
        authoritative_row_count=authoritative_row_count,
        table_digests=tuple(digests),
        hash_nodes=tuple(nodes),
    )


def classify_replay_failure(
    failure_code: str,
    detail: str,
    expected: Optional[str] = None,
    actual: Optional[str] = None,
) -> ReplayFailure:
    """Map replay mismatch into deterministic severity/scope classification."""
    severity, scope = _FAILURE_CLASSIFICATION.get(failure_code, ("MEDIUM", "unknown"))
    return ReplayFailure(
        failure_code=failure_code,
        severity=severity,
        scope=scope,
        detail=detail,
        expected=expected,
        actual=actual,
    )


def compare_replay_with_manifest(
    boundary: ReplaySnapshotBoundary,
    recomputed: ReplayDagResult,
) -> ReplayComparisonReport:
    """Compare recomputed replay DAG outputs against stored manifest surface."""
    failures: list[ReplayFailure] = []
    if boundary.manifest is None:
        failures.append(
            classify_replay_failure(
                "MANIFEST_MISSING",
                "No replay_manifest row found for replay key.",
            )
        )
        manifest_root_hash: Optional[str] = None
        manifest_row_count: Optional[int] = None
    else:
        manifest_root_hash = boundary.manifest.replay_root_hash
        manifest_row_count = boundary.manifest.authoritative_row_count
        if boundary.manifest.run_seed_hash != boundary.run_seed_hash:
            failures.append(
                classify_replay_failure(
                    "RUN_SEED_MISMATCH",
                    "run_seed_hash in replay_manifest does not match run_context.",
                    expected=boundary.run_seed_hash,
                    actual=boundary.manifest.run_seed_hash,
                )
            )
        if boundary.manifest.replay_root_hash != recomputed.root_hash:
            failures.append(
                classify_replay_failure(
                    "ROOT_HASH_MISMATCH",
                    "replay_root_hash in replay_manifest does not match recomputed DAG root.",
                    expected=recomputed.root_hash,
                    actual=boundary.manifest.replay_root_hash,
                )
            )
        if boundary.manifest.authoritative_row_count != recomputed.authoritative_row_count:
            failures.append(
                classify_replay_failure(
                    "ROW_COUNT_MISMATCH",
                    "authoritative_row_count does not match recomputed row surface count.",
                    expected=str(recomputed.authoritative_row_count),
                    actual=str(boundary.manifest.authoritative_row_count),
                )
            )

    if boundary.run_context_replay_root_hash != recomputed.root_hash:
        failures.append(
            classify_replay_failure(
                "RUN_CONTEXT_ROOT_MISMATCH",
                "run_context.replay_root_hash does not match recomputed DAG root.",
                expected=recomputed.root_hash,
                actual=boundary.run_context_replay_root_hash,
            )
        )

    return ReplayComparisonReport(
        replay_parity=not failures,
        mismatch_count=len(failures),
        failures=tuple(failures),
        recomputed_root_hash=recomputed.root_hash,
        manifest_root_hash=manifest_root_hash,
        recomputed_authoritative_row_count=recomputed.authoritative_row_count,
        manifest_authoritative_row_count=manifest_row_count,
    )


def replay_manifest_parity(
    db: ReplayHarnessDatabase,
    run_id: UUID,
    account_id: int,
    origin_hour_ts_utc: datetime,
) -> ReplayComparisonReport:
    """End-to-end Phase 2 deterministic replay parity check."""
    boundary = load_snapshot_boundary(
        db=db,
        run_id=run_id,
        account_id=account_id,
        origin_hour_ts_utc=origin_hour_ts_utc,
    )
    recomputed = recompute_hash_dag(db=db, boundary=boundary)
    return compare_replay_with_manifest(boundary=boundary, recomputed=recomputed)


def list_replay_targets(
    db: ReplayHarnessDatabase,
    account_id: int,
    run_mode: str,
    start_hour_ts_utc: datetime,
    end_hour_ts_utc: datetime,
    max_targets: Optional[int] = None,
) -> tuple[ReplayTarget, ...]:
    """List deterministic replay targets for an account/mode/hour window."""
    if end_hour_ts_utc < start_hour_ts_utc:
        raise DeterministicAbortError("end_hour_ts_utc must be >= start_hour_ts_utc.")

    rows = db.fetch_all(
        """
        SELECT run_id, account_id, run_mode, origin_hour_ts_utc
        FROM run_context
        WHERE account_id = :account_id
          AND run_mode = :run_mode
          AND origin_hour_ts_utc >= :start_hour_ts_utc
          AND origin_hour_ts_utc <= :end_hour_ts_utc
        ORDER BY origin_hour_ts_utc ASC, run_id ASC
        """,
        {
            "account_id": account_id,
            "run_mode": run_mode,
            "start_hour_ts_utc": start_hour_ts_utc,
            "end_hour_ts_utc": end_hour_ts_utc,
        },
    )

    if not rows:
        raise DeterministicAbortError(
            "No run_context rows found for replay target window."
        )

    targets = tuple(
        ReplayTarget(
            run_id=UUID(str(row["run_id"])),
            account_id=int(row["account_id"]),
            run_mode=str(row["run_mode"]),
            origin_hour_ts_utc=row["origin_hour_ts_utc"],
        )
        for row in rows
    )
    if max_targets is None:
        return targets
    if max_targets <= 0:
        raise DeterministicAbortError("max_targets must be > 0 when provided.")
    return targets[:max_targets]


def replay_manifest_window_parity(
    db: ReplayHarnessDatabase,
    account_id: int,
    run_mode: str,
    start_hour_ts_utc: datetime,
    end_hour_ts_utc: datetime,
    max_targets: Optional[int] = None,
) -> ReplayWindowReport:
    """Run Phase 2 parity checks over a deterministic replay target window."""
    targets = list_replay_targets(
        db=db,
        account_id=account_id,
        run_mode=run_mode,
        start_hour_ts_utc=start_hour_ts_utc,
        end_hour_ts_utc=end_hour_ts_utc,
        max_targets=max_targets,
    )
    items = tuple(
        ReplayWindowItem(
            target=target,
            report=replay_manifest_parity(
                db=db,
                run_id=target.run_id,
                account_id=target.account_id,
                origin_hour_ts_utc=target.origin_hour_ts_utc,
            ),
        )
        for target in targets
    )
    failed_targets = sum(1 for item in items if not item.report.replay_parity)
    total_targets = len(items)
    return ReplayWindowReport(
        replay_parity=(failed_targets == 0),
        total_targets=total_targets,
        passed_targets=total_targets - failed_targets,
        failed_targets=failed_targets,
        items=items,
    )


def _compute_table_digest(
    table_name: str,
    key_columns: tuple[str, ...],
    hash_column: str,
    rows: Sequence[Mapping[str, Any]],
    boundary_hash: str,
) -> ReplayTableDigest:
    sorted_rows = sorted(rows, key=lambda row: _row_sort_key(row, key_columns))
    canonical_rows = [
        {
            "keys": {column: row.get(column) for column in key_columns},
            "hash": row.get(hash_column),
        }
        for row in sorted_rows
    ]
    serialized = canonical_serialize({"table": table_name, "rows": canonical_rows})
    rowset_digest = stable_hash(
        (
            "phase_2_table_digest_v1",
            boundary_hash,
            table_name,
            str(len(canonical_rows)),
            serialized,
        )
    )
    return ReplayTableDigest(
        table_name=table_name,
        row_count=len(canonical_rows),
        rowset_digest=rowset_digest,
    )


def _row_sort_key(row: Mapping[str, Any], key_columns: Sequence[str]) -> tuple[str, ...]:
    return tuple(normalize_token(row.get(column)) for column in key_columns)


def _canonicalize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        ordered_items = sorted(value.items(), key=lambda item: str(item[0]))
        return {str(key): _canonicalize_value(inner) for key, inner in ordered_items}
    if isinstance(value, (list, tuple)):
        return [_canonicalize_value(inner) for inner in value]
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal("0.000000000000000001")), "f")
    if isinstance(value, datetime):
        return normalize_timestamp(value)
    if isinstance(value, UUID):
        return str(value)
    if value is None or isinstance(value, (bool, int, str)):
        return value
    return str(value)
