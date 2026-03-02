from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from execution.phase6.autonomy_daemon import Phase6AutonomyDaemon
from execution.phase6.common import Phase6Clock
from execution.phase6.phase6_config import Phase6Config
from tests.phase6.utils import FakeDB


class _FixedClock(Phase6Clock):
    def __init__(self, now_ts: datetime) -> None:
        self._now_ts = now_ts

    def now_utc(self) -> datetime:
        return self._now_ts


def _config(local_cache_dir: Path, **overrides) -> Phase6Config:  # type: ignore[no-untyped-def]
    base = dict(
        hist_market_data_provider="COINAPI",
        hist_market_data_api_key="k",
        hist_market_data_api_secret="",
        hist_market_data_base_url="https://rest.coinapi.io",
        kraken_public_base_url="https://api.kraken.com",
        universe_ranking_source="COINAPI",
        universe_refresh_cron="0 0 * * *",
        training_universe_version="UNIVERSE_V1_TOP30_NON_STABLE",
        local_data_cache_dir=local_cache_dir,
        force_local_data_for_training=True,
        allow_provider_calls_during_training=False,
        enable_continuous_ingestion=True,
        enable_autonomous_retraining=True,
        console_log_enabled=False,
        ingestion_loop_seconds=1,
        retrain_hour_utc=0,
        bootstrap_lookback_days=3650,
        api_budget_per_minute=10,
        min_free_disk_gb=0.0,
        adaptive_trade_poll_zero_streak=3,
        adaptive_trade_poll_interval_minutes=5,
        drift_accuracy_drop_pp=5.0,
        drift_ece_delta=0.03,
        drift_psi_threshold=0.25,
        drift_retrain_cooldown_minutes=360,
        drift_min_baseline_samples=24,
        promotion_local_branch="automation/phase6-promotions",
        daemon_lock_stale_seconds=900,
        daemon_failure_backoff_seconds=2,
        daemon_max_consecutive_failures=3,
    )
    base.update(overrides)
    return Phase6Config(**base)


def _daemon(
    db: FakeDB,
    *,
    local_cache_dir: Path,
    cfg: Phase6Config | None = None,
    now_hour: int = 0,
) -> Phase6AutonomyDaemon:
    clock = _FixedClock(datetime(2026, 1, 1, now_hour, tzinfo=timezone.utc))
    return Phase6AutonomyDaemon(
        db=db,
        provider=SimpleNamespace(),
        config=cfg or _config(local_cache_dir),
        symbols=("BTC", "ETH"),
        asset_id_by_symbol={"BTC": 1, "ETH": 2},
        clock=clock,
    )


def test_bootstrap_complete_and_status_paths(tmp_path: Path) -> None:
    db = FakeDB()
    d = _daemon(db, local_cache_dir=tmp_path)
    db.set_one("COUNT(DISTINCT symbol)", {"n": 1})
    assert d.bootstrap_complete() is False

    db.set_one("COUNT(DISTINCT symbol)", {"n": 2})
    assert d.bootstrap_complete() is True

    db.set_one("FROM ingestion_cycle", {"ingestion_cycle_id": "ic1"})
    db.set_one("FROM model_training_run", {"training_cycle_id": "tc_model", "status": "COMPLETED"})
    status = d.get_status()
    assert status.last_ingestion_cycle_id == "ic1"
    assert status.last_training_cycle_id == "tc_model"
    assert status.last_training_status == "COMPLETED"

    db_fallback = FakeDB()
    d_fallback = _daemon(db_fallback, local_cache_dir=tmp_path / "fallback")
    db_fallback.set_one("COUNT(DISTINCT symbol)", {"n": 0})
    db_fallback.set_one("FROM model_training_run", None)
    db_fallback.set_one(
        "FROM automation_event_log",
        {"status": "FAILED", "details": "cycle_id=tc_event,error=boom"},
    )
    status_fallback = d_fallback.get_status()
    assert status_fallback.last_training_cycle_id == "tc_event"
    assert status_fallback.last_training_status == "FAILED"


def test_lock_acquire_release_and_stale_recovery(tmp_path: Path) -> None:
    d = _daemon(FakeDB(), local_cache_dir=tmp_path)
    d.acquire_exclusive_lock()
    assert (tmp_path / ".phase6_daemon.lock").exists()
    d.release_exclusive_lock()
    assert not (tmp_path / ".phase6_daemon.lock").exists()

    stale_dir = tmp_path / "stale"
    stale_daemon = _daemon(FakeDB(), local_cache_dir=stale_dir)
    stale_dir.mkdir(parents=True, exist_ok=True)
    stale_payload = {
        "owner": "other",
        "heartbeat_at_utc": "2020-01-01T00:00:00Z",
    }
    (stale_dir / ".phase6_daemon.lock").write_text(json.dumps(stale_payload), encoding="utf-8")
    stale_daemon.acquire_exclusive_lock()
    stale_daemon.release_exclusive_lock()

    active_dir = tmp_path / "active"
    active = _daemon(FakeDB(), local_cache_dir=active_dir)
    active_dir.mkdir(parents=True, exist_ok=True)
    active_payload = {
        "owner": "another-owner",
        "heartbeat_at_utc": "2026-01-01T00:00:00Z",
    }
    (active_dir / ".phase6_daemon.lock").write_text(json.dumps(active_payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="already held"):
        active.acquire_exclusive_lock()


def test_run_operations_log_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDB()
    d = _daemon(db, local_cache_dir=tmp_path)

    monkeypatch.setattr("execution.phase6.autonomy_daemon.run_bootstrap_backfill", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(RuntimeError, match="x"):
        d.run_bootstrap_backfill(
            start_ts_utc=datetime(2025, 1, 1, tzinfo=timezone.utc),
            end_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    monkeypatch.setattr("execution.phase6.autonomy_daemon.run_incremental_sync", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("y")))
    with pytest.raises(RuntimeError, match="y"):
        d.run_incremental_sync()

    monkeypatch.setattr("execution.phase6.autonomy_daemon.repair_pending_gaps", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("z")))
    with pytest.raises(RuntimeError, match="z"):
        d.run_gap_repair()

    monkeypatch.setattr("execution.phase6.autonomy_daemon.run_training_cycle", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("t")))
    with pytest.raises(RuntimeError, match="t"):
        d.run_training(cycle_kind="MANUAL")

    assert len(db.executed) >= 4


def test_run_training_invalid_config_rejected(tmp_path: Path) -> None:
    cfg = _config(tmp_path, force_local_data_for_training=True, allow_provider_calls_during_training=True)
    d = _daemon(FakeDB(), local_cache_dir=tmp_path, cfg=cfg)
    with pytest.raises(RuntimeError, match="local-only training"):
        d.run_training(cycle_kind="MANUAL")


def test_maybe_trigger_drift_training_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = _daemon(FakeDB(), local_cache_dir=tmp_path)
    monkeypatch.setattr(
        d,
        "_compute_drift_observation",
        lambda _now: SimpleNamespace(accuracy_drop_pp=Decimal("0"), ece_delta=Decimal("0"), psi_value=Decimal("0")),
    )
    monkeypatch.setattr("execution.phase6.autonomy_daemon.persist_drift_event", lambda *_args, **_kwargs: False)
    assert d.maybe_trigger_drift_training() is False

    calls: list[str] = []
    monkeypatch.setattr("execution.phase6.autonomy_daemon.persist_drift_event", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(d, "_drift_retrain_recently_ran", lambda _now: True)
    monkeypatch.setattr(d, "run_training", lambda cycle_kind="": calls.append(cycle_kind))
    assert d.maybe_trigger_drift_training() is False
    assert calls == []

    monkeypatch.setattr(d, "_drift_retrain_recently_ran", lambda _now: False)
    assert d.maybe_trigger_drift_training() is True
    assert calls == ["DRIFT_TRIGGERED"]


def test_run_once_and_daemon_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = _daemon(FakeDB(), local_cache_dir=tmp_path, now_hour=0)
    calls: list[str] = []
    monkeypatch.setattr(d, "run_incremental_sync", lambda: calls.append("sync"))
    monkeypatch.setattr(d, "run_gap_repair", lambda: calls.append("repair"))
    monkeypatch.setattr(d, "bootstrap_complete", lambda: True)
    monkeypatch.setattr(d, "_scheduled_training_already_ran_today", lambda _now: False)
    monkeypatch.setattr(d, "run_training", lambda cycle_kind="": calls.append(f"train:{cycle_kind}"))
    d.run_once()
    assert calls == ["sync", "repair", "train:SCHEDULED"]

    d2 = _daemon(FakeDB(), local_cache_dir=tmp_path / "d2", now_hour=0)
    calls2: list[str] = []
    monkeypatch.setattr(d2, "run_incremental_sync", lambda: calls2.append("sync"))
    monkeypatch.setattr(d2, "run_gap_repair", lambda: calls2.append("repair"))
    monkeypatch.setattr(d2, "bootstrap_complete", lambda: True)
    monkeypatch.setattr(d2, "_scheduled_training_already_ran_today", lambda _now: True)
    monkeypatch.setattr(d2, "run_training", lambda cycle_kind="": calls2.append(f"train:{cycle_kind}"))
    monkeypatch.setattr(d2, "maybe_trigger_drift_training", lambda: calls2.append("drift") or False)
    d2.run_once()
    assert calls2 == ["sync", "repair"]

    sleep_calls: list[int] = []
    d3 = _daemon(FakeDB(), local_cache_dir=tmp_path / "d3", cfg=_config(tmp_path / "d3", ingestion_loop_seconds=7))
    loop_counter = {"n": 0}

    def _loop_once() -> None:
        loop_counter["n"] += 1

    monkeypatch.setattr(d3, "_run_once_cycle", _loop_once)
    monkeypatch.setattr("execution.phase6.autonomy_daemon.time.sleep", lambda seconds: sleep_calls.append(seconds))
    d3.daemon_loop(max_cycles=2)
    assert loop_counter["n"] == 2
    assert sleep_calls == [7]


def test_daemon_loop_failure_backoff_and_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config(tmp_path, daemon_failure_backoff_seconds=5, daemon_max_consecutive_failures=2)
    d = _daemon(FakeDB(), local_cache_dir=tmp_path, cfg=cfg)
    monkeypatch.setattr(d, "_run_once_cycle", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    sleep_calls: list[int] = []
    monkeypatch.setattr("execution.phase6.autonomy_daemon.time.sleep", lambda seconds: sleep_calls.append(seconds))
    with pytest.raises(RuntimeError, match="exceeded max consecutive failures"):
        d.daemon_loop(max_cycles=10)
    assert sleep_calls == [5]
    assert not (tmp_path / ".phase6_daemon.lock").exists()


def test_drift_observation_and_feature_psi_math(tmp_path: Path) -> None:
    db = FakeDB()
    d = _daemon(db, local_cache_dir=tmp_path)

    db.set_one(
        "AND measured_at_utc >= :recent_start",
        {"sample_count": 24, "avg_accuracy": Decimal("0.50"), "avg_ece": Decimal("0.05")},
    )
    db.set_one(
        "AND measured_at_utc < :recent_start",
        {"sample_count": 48, "avg_accuracy": Decimal("0.60"), "avg_ece": Decimal("0.02")},
    )
    db.set_all(
        "FROM dataset_snapshot\n            ORDER BY generated_at_utc DESC",
        [
            {"dataset_snapshot_id": "new"},
            {"dataset_snapshot_id": "old"},
        ],
    )
    db.set_all(
        "FROM dataset_snapshot_component",
        [
            {"dataset_snapshot_id": "new", "symbol": "BTC", "component_row_count": 60},
            {"dataset_snapshot_id": "new", "symbol": "ETH", "component_row_count": 40},
            {"dataset_snapshot_id": "old", "symbol": "BTC", "component_row_count": 50},
            {"dataset_snapshot_id": "old", "symbol": "ETH", "component_row_count": 50},
        ],
    )

    obs = d._compute_drift_observation(datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert obs.accuracy_drop_pp == Decimal("10.00")
    assert obs.ece_delta == Decimal("0.03")
    assert obs.psi_value > Decimal("0")

    db_min = FakeDB()
    d_min = _daemon(db_min, local_cache_dir=tmp_path / "min")
    db_min.set_one(
        "AND measured_at_utc >= :recent_start",
        {"sample_count": 0, "avg_accuracy": Decimal("0"), "avg_ece": Decimal("0")},
    )
    db_min.set_one(
        "AND measured_at_utc < :recent_start",
        {"sample_count": 0, "avg_accuracy": Decimal("0"), "avg_ece": Decimal("0")},
    )
    obs_min = d_min._compute_drift_observation(datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert obs_min.accuracy_drop_pp == 0
    assert obs_min.ece_delta == 0
    assert obs_min.psi_value == 0


def test_helper_parsers_and_extract_cycle_id(tmp_path: Path) -> None:
    d = _daemon(FakeDB(), local_cache_dir=tmp_path)
    assert d._to_decimal(None) == Decimal("0")
    assert d._to_decimal("1.25") == Decimal("1.25")
    assert d._parse_utc(None) is None
    assert d._parse_utc("   ") is None
    parsed = d._parse_utc("2026-01-01T00:00:00Z")
    assert parsed is not None
    assert parsed.tzinfo is not None
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert d._parse_utc(dt) == dt
    assert d._extract_cycle_id(None) is None
    assert d._extract_cycle_id("status=ok") is None
    assert d._extract_cycle_id("cycle_id=abc123,reason=x") == "abc123"
    assert d._extract_cycle_id("prefix cycle_id=abc123") == "abc123"


def test_safe_log_event_swallow_and_lock_payload_reading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = _daemon(FakeDB(), local_cache_dir=tmp_path)
    monkeypatch.setattr(d, "_log_event", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    d._safe_log_event("X", "FAILED", "details")

    assert d._read_lock_payload() is None
    lock_path = tmp_path / ".phase6_daemon.lock"
    lock_path.write_text("{bad json", encoding="utf-8")
    assert d._read_lock_payload() is None
    lock_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert d._read_lock_payload() is None


def test_lock_depth_refresh_and_release_edge_paths(tmp_path: Path) -> None:
    d = _daemon(FakeDB(), local_cache_dir=tmp_path)
    now_utc = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert d._lock_payload_is_stale({"owner": "x"}, now_utc) is True

    d.acquire_exclusive_lock()
    d.acquire_exclusive_lock()
    assert d._lock_depth == 2
    d.release_exclusive_lock()
    assert d._lock_depth == 1
    d.release_exclusive_lock()
    assert d._lock_depth == 0
    d.release_exclusive_lock()
    d._refresh_lock_heartbeat()

    d._lock_depth = 1
    with pytest.raises(RuntimeError, match="disappeared"):
        d._refresh_lock_heartbeat()
    lock_path = tmp_path / ".phase6_daemon.lock"
    lock_path.write_text(json.dumps({"owner": "someone-else", "heartbeat_at_utc": "2026-01-01T00:00:00Z"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="ownership changed"):
        d._refresh_lock_heartbeat()


def test_lock_retry_exhaustion_and_release_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = _daemon(FakeDB(), local_cache_dir=tmp_path)
    stale_payload = {"owner": "other", "heartbeat_at_utc": "2020-01-01T00:00:00Z"}
    monkeypatch.setattr(d, "_read_lock_payload", lambda: stale_payload)
    monkeypatch.setattr("execution.phase6.autonomy_daemon.os.open", lambda *_args, **_kwargs: (_ for _ in ()).throw(FileExistsError()))
    monkeypatch.setattr("execution.phase6.autonomy_daemon.os.remove", lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()))
    with pytest.raises(RuntimeError, match="Failed to acquire"):
        d.acquire_exclusive_lock()

    d2 = _daemon(FakeDB(), local_cache_dir=tmp_path / "release")
    d2._lock_depth = 1
    monkeypatch.setattr(d2, "_read_lock_payload", lambda: {"owner": d2._lock_owner})
    monkeypatch.setattr("execution.phase6.autonomy_daemon.os.remove", lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()))
    d2.release_exclusive_lock()
    assert d2._lock_depth == 0

    d3 = _daemon(FakeDB(), local_cache_dir=tmp_path / "release-other")
    d3._lock_depth = 1
    monkeypatch.setattr(d3, "_read_lock_payload", lambda: {"owner": "different-owner"})
    d3.release_exclusive_lock()
    assert d3._lock_depth == 0


def test_run_operation_success_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDB()
    d = _daemon(db, local_cache_dir=tmp_path)
    d._provider = SimpleNamespace(call_count=5)  # type: ignore[assignment]
    monkeypatch.setattr(
        "execution.phase6.autonomy_daemon.run_bootstrap_backfill",
        lambda **_kwargs: SimpleNamespace(
            ingestion_cycle_id="boot-1",
            completed=False,
            symbols_completed=1,
            bars_written=10,
            trades_archived=20,
        ),
    )
    with pytest.raises(RuntimeError, match="did not complete"):
        d.run_bootstrap_backfill(
            start_ts_utc=datetime(2025, 1, 1, tzinfo=timezone.utc),
            end_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    monkeypatch.setattr(
        "execution.phase6.autonomy_daemon.run_bootstrap_backfill",
        lambda **_kwargs: SimpleNamespace(
            ingestion_cycle_id="boot-2",
            completed=True,
            symbols_completed=2,
            bars_written=11,
            trades_archived=22,
        ),
    )
    d.run_bootstrap_backfill(
        start_ts_utc=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    def _sync_success(**_kwargs):  # type: ignore[no-untyped-def]
        d._provider.call_count = 8  # type: ignore[attr-defined]
        return SimpleNamespace(
            ingestion_cycle_id="ic-success",
            symbols_synced=2,
            symbols_throttled=1,
            bars_written=3,
            trades_archived=4,
            ohlcv_api_calls=2,
            trade_api_calls=2,
        )

    monkeypatch.setattr("execution.phase6.autonomy_daemon.run_incremental_sync", _sync_success)
    d.run_incremental_sync()
    monkeypatch.setattr(
        "execution.phase6.autonomy_daemon.repair_pending_gaps",
        lambda **_kwargs: SimpleNamespace(repaired_count=2, failed_count=0),
    )
    d.run_gap_repair()
    monkeypatch.setattr(
        "execution.phase6.autonomy_daemon.run_training_cycle",
        lambda **_kwargs: SimpleNamespace(
            approved=True,
            training_cycle_id="tc",
            reason_code="APPROVED",
            dataset_snapshot_id="ds1",
            candidate_model_set_hash="cand",
        ),
    )
    d.run_training(cycle_kind="MANUAL")


def test_schedule_cooldown_and_status_none_paths(tmp_path: Path) -> None:
    db = FakeDB()
    d = _daemon(db, local_cache_dir=tmp_path)
    now_utc = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.set_one("FROM training_cycle\n            WHERE cycle_kind = 'SCHEDULED'", {"n": 1})
    assert d._scheduled_training_already_ran_today(now_utc) is True
    db.set_one("FROM training_cycle\n            WHERE cycle_kind = 'SCHEDULED'", None)
    assert d._scheduled_training_already_ran_today(now_utc) is False
    db.set_one("FROM training_cycle\n            WHERE cycle_kind = 'DRIFT_TRIGGERED'", {"n": 1})
    assert d._drift_retrain_recently_ran(now_utc) is True
    db.set_one("FROM training_cycle\n            WHERE cycle_kind = 'DRIFT_TRIGGERED'", None)
    assert d._drift_retrain_recently_ran(now_utc) is False

    db.set_one("FROM ingestion_cycle", None)
    db.set_one("FROM model_training_run", None)
    db.set_one("WHERE event_type = 'TRAINING'", None)
    status = d.get_status()
    assert status.last_training_cycle_id is None
    assert status.last_training_status is None


def test_feature_psi_edge_paths(tmp_path: Path) -> None:
    db_short = FakeDB()
    d_short = _daemon(db_short, local_cache_dir=tmp_path / "short")
    db_short.set_all(
        "FROM dataset_snapshot\n            ORDER BY generated_at_utc DESC",
        [{"dataset_snapshot_id": "only-one"}],
    )
    assert d_short._compute_feature_psi() == Decimal("0")

    db_zero = FakeDB()
    d_zero = _daemon(db_zero, local_cache_dir=tmp_path / "zero")
    db_zero.set_all(
        "FROM dataset_snapshot\n            ORDER BY generated_at_utc DESC",
        [{"dataset_snapshot_id": "new"}, {"dataset_snapshot_id": "old"}],
    )
    db_zero.set_all(
        "FROM dataset_snapshot_component",
        [
            {"dataset_snapshot_id": "other", "symbol": "BTC", "component_row_count": 10},
            {"dataset_snapshot_id": "new", "symbol": "BTC", "component_row_count": 0},
            {"dataset_snapshot_id": "old", "symbol": "BTC", "component_row_count": 0},
        ],
    )
    assert d_zero._compute_feature_psi() == Decimal("0")


def test_run_once_cycle_branch_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config(tmp_path, enable_continuous_ingestion=False, retrain_hour_utc=0)
    d = _daemon(FakeDB(), local_cache_dir=tmp_path, cfg=cfg, now_hour=1)
    calls: list[str] = []
    monkeypatch.setattr(d, "run_incremental_sync", lambda: calls.append("sync"))
    monkeypatch.setattr(d, "run_gap_repair", lambda: calls.append("repair"))
    monkeypatch.setattr(d, "bootstrap_complete", lambda: True)
    monkeypatch.setattr(d, "maybe_trigger_drift_training", lambda: calls.append("drift") or True)
    d._run_once_cycle()
    assert calls == ["repair", "drift"]

    d_no_bootstrap = _daemon(FakeDB(), local_cache_dir=tmp_path / "noboot", cfg=cfg, now_hour=1)
    calls_no_bootstrap: list[str] = []
    monkeypatch.setattr(d_no_bootstrap, "run_gap_repair", lambda: calls_no_bootstrap.append("repair"))
    monkeypatch.setattr(d_no_bootstrap, "run_bootstrap_backfill", lambda **_kwargs: calls_no_bootstrap.append("bootstrap"))
    monkeypatch.setattr(d_no_bootstrap, "bootstrap_complete", lambda: False)
    d_no_bootstrap._run_once_cycle()
    assert calls_no_bootstrap == ["bootstrap"]

    cfg_disabled = _config(tmp_path / "disabled", enable_autonomous_retraining=False)
    d_disabled = _daemon(FakeDB(), local_cache_dir=tmp_path / "disabled", cfg=cfg_disabled, now_hour=1)
    calls_disabled: list[str] = []
    monkeypatch.setattr(d_disabled, "run_incremental_sync", lambda: calls_disabled.append("sync"))
    monkeypatch.setattr(d_disabled, "run_gap_repair", lambda: calls_disabled.append("repair"))
    monkeypatch.setattr(d_disabled, "bootstrap_complete", lambda: True)
    d_disabled._run_once_cycle()
    assert calls_disabled == ["sync", "repair"]


def test_manual_training_with_data_refresh_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config(tmp_path, min_free_disk_gb=0.0, bootstrap_lookback_days=30)
    d = _daemon(FakeDB(), local_cache_dir=tmp_path, cfg=cfg, now_hour=1)
    calls: list[str] = []
    monkeypatch.setattr(d, "bootstrap_complete", lambda: False)
    monkeypatch.setattr(d, "run_bootstrap_backfill", lambda **_kwargs: calls.append("bootstrap"))
    monkeypatch.setattr(d, "run_incremental_sync", lambda: calls.append("sync"))
    monkeypatch.setattr(d, "run_gap_repair", lambda: calls.append("repair"))
    monkeypatch.setattr(d, "run_training", lambda cycle_kind="": calls.append(f"train:{cycle_kind}"))
    d.run_manual_training_with_data_refresh()
    assert calls == ["bootstrap", "sync", "repair", "train:MANUAL"]

    d2 = _daemon(FakeDB(), local_cache_dir=tmp_path / "done", cfg=cfg, now_hour=1)
    calls2: list[str] = []
    monkeypatch.setattr(d2, "bootstrap_complete", lambda: True)
    monkeypatch.setattr(d2, "run_bootstrap_backfill", lambda **_kwargs: calls2.append("bootstrap"))
    monkeypatch.setattr(d2, "run_incremental_sync", lambda: calls2.append("sync"))
    monkeypatch.setattr(d2, "run_gap_repair", lambda: calls2.append("repair"))
    monkeypatch.setattr(d2, "run_training", lambda cycle_kind="": calls2.append(f"train:{cycle_kind}"))
    d2.run_manual_training_with_data_refresh()
    assert calls2 == ["sync", "repair", "train:MANUAL"]


def test_console_and_provider_call_count_paths(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config(tmp_path / "console", console_log_enabled=True)
    d = _daemon(FakeDB(), local_cache_dir=tmp_path / "console", cfg=cfg)
    d._console_log("hello")
    assert "hello" in capsys.readouterr().out

    provider = SimpleNamespace(call_count=17)
    d_count = Phase6AutonomyDaemon(
        db=FakeDB(),
        provider=provider,
        config=cfg,
        symbols=("BTC",),
        asset_id_by_symbol={"BTC": 1},
        clock=_FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
    )
    assert d_count._provider_call_count() == 17
    provider.call_count = "bad"
    assert d_count._provider_call_count() is None

    monkeypatch.setattr(d_count, "_log_event", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("x")))
    d_count._safe_log_event("INGESTION", "FAILED", "detail")
    assert "event_log_persist_failed" in capsys.readouterr().out


def test_run_incremental_sync_without_provider_call_counter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = _daemon(FakeDB(), local_cache_dir=tmp_path)
    monkeypatch.setattr(
        "execution.phase6.autonomy_daemon.run_incremental_sync",
        lambda **_kwargs: SimpleNamespace(
            ingestion_cycle_id="ic-none",
            symbols_synced=1,
            symbols_throttled=0,
            bars_written=1,
            trades_archived=2,
            ohlcv_api_calls=1,
            trade_api_calls=1,
        ),
    )
    d.run_incremental_sync()


def test_resource_guard_failures_stop_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config(tmp_path / "guard", min_free_disk_gb=5.0)
    d = _daemon(FakeDB(), local_cache_dir=tmp_path / "guard", cfg=cfg)
    monkeypatch.setattr("execution.phase6.autonomy_daemon.shutil.disk_usage", lambda _p: SimpleNamespace(free=1024))
    with pytest.raises(RuntimeError, match="Insufficient free disk space"):
        d.run_incremental_sync()
