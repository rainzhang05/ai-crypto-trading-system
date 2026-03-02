from __future__ import annotations

from datetime import datetime, timezone
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


def _config(**overrides) -> Phase6Config:  # type: ignore[no-untyped-def]
    base = dict(
        hist_market_data_provider="COINAPI",
        hist_market_data_api_key="k",
        hist_market_data_api_secret="",
        hist_market_data_base_url="https://rest.coinapi.io",
        kraken_public_base_url="https://api.kraken.com",
        universe_ranking_source="COINAPI",
        universe_refresh_cron="0 0 * * *",
        training_universe_version="UNIVERSE_V1_TOP30_NON_STABLE",
        local_data_cache_dir=Path("."),
        force_local_data_for_training=True,
        allow_provider_calls_during_training=False,
        enable_continuous_ingestion=True,
        enable_autonomous_retraining=True,
        ingestion_loop_seconds=1,
        retrain_hour_utc=0,
        api_budget_per_minute=10,
        drift_accuracy_drop_pp=5.0,
        drift_ece_delta=0.03,
        drift_psi_threshold=0.25,
        promotion_local_branch="automation/phase6-promotions",
    )
    base.update(overrides)
    return Phase6Config(**base)


def _daemon(db: FakeDB, cfg: Phase6Config | None = None, now_hour: int = 0) -> Phase6AutonomyDaemon:
    clock = _FixedClock(datetime(2026, 1, 1, now_hour, tzinfo=timezone.utc))
    return Phase6AutonomyDaemon(
        db=db,
        provider=SimpleNamespace(),
        config=cfg or _config(),
        symbols=("BTC", "ETH"),
        asset_id_by_symbol={"BTC": 1, "ETH": 2},
        clock=clock,
    )


def test_bootstrap_complete_and_status_paths() -> None:
    db = FakeDB()
    d = _daemon(db)
    db.set_one("COUNT(DISTINCT symbol)", {"n": 1})
    assert d.bootstrap_complete() is False

    db.set_one("COUNT(DISTINCT symbol)", {"n": 2})
    assert d.bootstrap_complete() is True

    db.set_one("FROM ingestion_cycle", {"ingestion_cycle_id": "ic1"})
    db.set_one("FROM training_cycle", {"training_cycle_id": "tc1", "status": "COMPLETED"})
    status = d.get_status()
    assert status.last_ingestion_cycle_id == "ic1"
    assert status.last_training_cycle_id == "tc1"
    assert status.last_training_status == "COMPLETED"


def test_run_bootstrap_backfill_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDB()
    d = _daemon(db)
    monkeypatch.setattr(
        "execution.phase6.autonomy_daemon.run_bootstrap_backfill",
        lambda **_kwargs: SimpleNamespace(completed=True, symbols_completed=2),
    )
    d.run_bootstrap_backfill(
        start_ts_utc=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert len(db.executed) >= 2

    d_fail = _daemon(FakeDB())
    monkeypatch.setattr(
        "execution.phase6.autonomy_daemon.run_bootstrap_backfill",
        lambda **_kwargs: SimpleNamespace(completed=False, symbols_completed=1),
    )
    with pytest.raises(RuntimeError, match="did not complete"):
        d_fail.run_bootstrap_backfill(
            start_ts_utc=datetime(2025, 1, 1, tzinfo=timezone.utc),
            end_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_incremental_gap_training_and_drift_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDB()
    d = _daemon(db)

    monkeypatch.setattr(
        "execution.phase6.autonomy_daemon.run_incremental_sync",
        lambda **_kwargs: SimpleNamespace(ingestion_cycle_id="ic1"),
    )
    d.run_incremental_sync()

    monkeypatch.setattr(
        "execution.phase6.autonomy_daemon.repair_pending_gaps",
        lambda **_kwargs: SimpleNamespace(repaired_count=1, failed_count=0),
    )
    d.run_gap_repair()

    monkeypatch.setattr(
        "execution.phase6.autonomy_daemon.run_training_cycle",
        lambda **_kwargs: SimpleNamespace(training_cycle_id="tc1", approved=True, reason_code="APPROVED"),
    )
    d.run_training(cycle_kind="MANUAL")

    triggered_calls: list[str] = []
    monkeypatch.setattr(
        "execution.phase6.autonomy_daemon.persist_drift_event",
        lambda *_args, **_kwargs: False,
    )
    assert d.maybe_trigger_drift_training() is False

    monkeypatch.setattr(
        "execution.phase6.autonomy_daemon.persist_drift_event",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(d, "run_training", lambda cycle_kind="": triggered_calls.append(cycle_kind))
    assert d.maybe_trigger_drift_training() is True
    assert triggered_calls == ["DRIFT_TRIGGERED"]


def test_run_training_invalid_config_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config(force_local_data_for_training=True, allow_provider_calls_during_training=True)
    d = _daemon(FakeDB(), cfg=cfg)
    with pytest.raises(RuntimeError, match="local-only training"):
        d.run_training(cycle_kind="MANUAL")

    d_reject = _daemon(FakeDB())
    monkeypatch.setattr(
        "execution.phase6.autonomy_daemon.run_training_cycle",
        lambda **_kwargs: SimpleNamespace(training_cycle_id="tc1", approved=False, reason_code="NOPE"),
    )
    d_reject.run_training(cycle_kind="MANUAL")


def test_run_once_and_daemon_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    d = _daemon(FakeDB(), now_hour=0)
    calls: list[str] = []
    monkeypatch.setattr(d, "run_incremental_sync", lambda: calls.append("sync"))
    monkeypatch.setattr(d, "run_gap_repair", lambda: calls.append("repair"))
    monkeypatch.setattr(d, "bootstrap_complete", lambda: True)
    monkeypatch.setattr(d, "run_training", lambda cycle_kind="": calls.append(f"train:{cycle_kind}"))
    d.run_once()
    assert calls == ["sync", "repair", "train:SCHEDULED"]

    d2 = _daemon(FakeDB(), cfg=_config(enable_continuous_ingestion=False), now_hour=3)
    calls2: list[str] = []
    monkeypatch.setattr(d2, "run_gap_repair", lambda: calls2.append("repair"))
    monkeypatch.setattr(d2, "bootstrap_complete", lambda: True)
    monkeypatch.setattr(d2, "maybe_trigger_drift_training", lambda: calls2.append("drift") or False)
    d2.run_once()
    assert calls2 == ["repair", "drift"]

    d3 = _daemon(FakeDB(), now_hour=2)
    calls3: list[str] = []
    monkeypatch.setattr(d3, "run_incremental_sync", lambda: calls3.append("sync"))
    monkeypatch.setattr(d3, "run_gap_repair", lambda: calls3.append("repair"))
    monkeypatch.setattr(d3, "bootstrap_complete", lambda: False)
    monkeypatch.setattr(d3, "run_training", lambda cycle_kind="": calls3.append(f"train:{cycle_kind}"))
    monkeypatch.setattr(d3, "maybe_trigger_drift_training", lambda: calls3.append("drift") or False)
    d3.run_once()
    assert calls3 == ["sync", "repair"]

    sleep_calls: list[int] = []
    monkeypatch.setattr("execution.phase6.autonomy_daemon.time.sleep", lambda seconds: sleep_calls.append(seconds))
    d.daemon_loop(max_cycles=1)
    assert sleep_calls == []

    loop_calls: list[str] = []
    d_loop = _daemon(FakeDB(), cfg=_config(ingestion_loop_seconds=7))
    monkeypatch.setattr(d_loop, "run_once", lambda: loop_calls.append("run"))
    d_loop.daemon_loop(max_cycles=2)
    assert loop_calls == ["run", "run"]
    assert sleep_calls[-1] == 7
