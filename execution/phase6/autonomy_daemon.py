"""Single-process autonomous Phase 6 daemon orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import socket
import time
from typing import Any, Mapping, Sequence

from execution.decision_engine import stable_hash
from execution.phase6.bootstrap_backfill import run_bootstrap_backfill
from execution.phase6.common import Phase6Clock, Phase6Database, ensure_dir
from execution.phase6.drift_monitor import DriftObservation, DriftThresholds, persist_drift_event
from execution.phase6.gap_repair import repair_pending_gaps
from execution.phase6.incremental_sync import run_incremental_sync
from execution.phase6.phase6_config import Phase6Config
from execution.phase6.provider_contract import HistoricalProvider
from execution.phase6.training_pipeline import run_training_cycle


@dataclass(frozen=True)
class DaemonStatus:
    """User-facing daemon status payload."""

    bootstrap_complete: bool
    universe_symbol_count: int
    last_ingestion_cycle_id: str | None
    last_training_cycle_id: str | None
    last_training_status: str | None


class Phase6AutonomyDaemon:
    """Deterministic autonomy loop for ingestion + training orchestration."""

    def __init__(
        self,
        *,
        db: Phase6Database,
        provider: HistoricalProvider,
        config: Phase6Config,
        symbols: Sequence[str],
        asset_id_by_symbol: dict[str, int],
        clock: Phase6Clock | None = None,
    ) -> None:
        self._db = db
        self._provider = provider
        self._config = config
        self._symbols = tuple(sorted(symbols))
        self._asset_id_by_symbol = dict(asset_id_by_symbol)
        self._clock = clock or Phase6Clock()

        self._lock_file_path = self._config.local_data_cache_dir / ".phase6_daemon.lock"
        self._lock_depth = 0
        self._lock_owner = stable_hash(
            (
                "phase6_daemon_lock_owner",
                socket.gethostname(),
                os.getpid(),
                id(self),
            )
        )

    @staticmethod
    def _to_decimal(value: Any) -> Decimal:
        if value is None:
            return Decimal("0")
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @staticmethod
    def _parse_utc(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc)
        text = str(value).strip()
        if not text:
            return None
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).astimezone(timezone.utc)

    def _safe_log_event(self, event_type: str, status: str, details: str) -> None:
        try:
            self._log_event(event_type, status, details)
        except Exception:
            return

    def _log_event(self, event_type: str, status: str, details: str) -> None:
        ts = self._clock.now_utc()
        row_hash = stable_hash(("automation_event_log", event_type, status, ts.isoformat(), details))
        self._db.execute(
            """
            INSERT INTO automation_event_log (
                event_ts_utc, event_type, status, details, row_hash
            ) VALUES (
                :event_ts_utc, :event_type, :status, :details, :row_hash
            )
            """,
            {
                "event_ts_utc": ts,
                "event_type": event_type,
                "status": status,
                "details": details,
                "row_hash": row_hash,
            },
        )

    def _read_lock_payload(self) -> Mapping[str, Any] | None:
        if not self._lock_file_path.exists():
            return None
        try:
            payload = json.loads(self._lock_file_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _write_lock_payload(self, payload: Mapping[str, Any]) -> None:
        ensure_dir(self._lock_file_path.parent)
        temp_path = self._lock_file_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(dict(payload), sort_keys=True), encoding="utf-8")
        os.replace(temp_path, self._lock_file_path)

    def _lock_payload_is_stale(self, payload: Mapping[str, Any], now_utc: datetime) -> bool:
        heartbeat = self._parse_utc(payload.get("heartbeat_at_utc")) or self._parse_utc(payload.get("acquired_at_utc"))
        if heartbeat is None:
            return True
        age_seconds = (now_utc - heartbeat).total_seconds()
        return age_seconds > float(self._config.daemon_lock_stale_seconds)

    def acquire_exclusive_lock(self) -> None:
        """Acquire process lock to prevent concurrent daemon instances."""
        if self._lock_depth > 0:
            self._lock_depth += 1
            self._refresh_lock_heartbeat()
            return

        now_utc = self._clock.now_utc().astimezone(timezone.utc)
        payload = {
            "owner": self._lock_owner,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "acquired_at_utc": now_utc.isoformat().replace("+00:00", "Z"),
            "heartbeat_at_utc": now_utc.isoformat().replace("+00:00", "Z"),
        }
        ensure_dir(self._lock_file_path.parent)

        for _ in range(3):
            try:
                fd = os.open(self._lock_file_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                existing = self._read_lock_payload()
                if existing is None or self._lock_payload_is_stale(existing, now_utc):
                    try:
                        os.remove(self._lock_file_path)
                    except FileNotFoundError:
                        pass
                    continue
                owner = str(existing.get("owner", "unknown"))
                raise RuntimeError(f"Phase 6 daemon lock is already held by owner={owner}")
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, sort_keys=True)
                self._lock_depth = 1
                self._safe_log_event("DAEMON_LOCK", "ACQUIRED", f"path={self._lock_file_path}")
                return

        raise RuntimeError("Failed to acquire Phase 6 daemon lock after stale-lock retries")

    def _refresh_lock_heartbeat(self) -> None:
        if self._lock_depth <= 0:
            return
        payload = self._read_lock_payload()
        if payload is None:
            raise RuntimeError("Phase 6 daemon lock file disappeared while lock is held")
        if str(payload.get("owner")) != self._lock_owner:
            raise RuntimeError("Phase 6 daemon lock ownership changed unexpectedly")
        now_utc = self._clock.now_utc().astimezone(timezone.utc)
        updated = dict(payload)
        updated["heartbeat_at_utc"] = now_utc.isoformat().replace("+00:00", "Z")
        self._write_lock_payload(updated)

    def release_exclusive_lock(self) -> None:
        """Release process lock, supporting nested acquisition depth."""
        if self._lock_depth <= 0:
            return
        if self._lock_depth > 1:
            self._lock_depth -= 1
            return

        payload = self._read_lock_payload()
        try:
            if payload is not None and str(payload.get("owner")) == self._lock_owner:
                os.remove(self._lock_file_path)
        except FileNotFoundError:
            pass
        finally:
            self._lock_depth = 0
            self._safe_log_event("DAEMON_LOCK", "RELEASED", f"path={self._lock_file_path}")

    def bootstrap_complete(self) -> bool:
        """Return True when all universe symbols have bootstrap watermark rows."""
        row = self._db.fetch_one(
            """
            SELECT COUNT(DISTINCT symbol) AS n
            FROM ingestion_watermark_history
            WHERE source_name = 'COINAPI'
              AND watermark_kind = 'BOOTSTRAP_END'
              AND symbol = ANY(:symbols)
            """,
            {"symbols": list(self._symbols)},
        )
        count = int(row["n"]) if row is not None else 0
        return count == len(self._symbols)

    def run_bootstrap_backfill(self, *, start_ts_utc: datetime, end_ts_utc: datetime) -> None:
        """Run mandatory strict bootstrap backfill."""
        self._log_event("BOOTSTRAP", "STARTED", f"window={start_ts_utc.isoformat()}..{end_ts_utc.isoformat()}")
        try:
            result = run_bootstrap_backfill(
                db=self._db,
                provider=self._provider,
                universe_symbols=self._symbols,
                asset_id_by_symbol=self._asset_id_by_symbol,
                local_cache_dir=str(self._config.local_data_cache_dir),
                start_ts_utc=start_ts_utc,
                end_ts_utc=end_ts_utc,
            )
        except Exception as exc:
            self._log_event("BOOTSTRAP", "FAILED", f"error={type(exc).__name__}:{exc}")
            raise
        status = "COMPLETED" if result.completed else "FAILED"
        self._log_event("BOOTSTRAP", status, f"symbols_completed={result.symbols_completed}")
        if not result.completed:
            raise RuntimeError("Bootstrap backfill did not complete for all universe symbols")

    def run_incremental_sync(self) -> None:
        """Run one incremental ingestion cycle."""
        now_utc = self._clock.now_utc()
        self._log_event("INGESTION", "STARTED", now_utc.isoformat())
        try:
            result = run_incremental_sync(
                db=self._db,
                provider=self._provider,
                symbols=self._symbols,
                asset_id_by_symbol=self._asset_id_by_symbol,
                local_cache_dir=self._config.local_data_cache_dir,
                now_utc=now_utc,
            )
        except Exception as exc:
            self._log_event("INGESTION", "FAILED", f"error={type(exc).__name__}:{exc}")
            raise
        self._log_event("INGESTION", "COMPLETED", f"cycle_id={result.ingestion_cycle_id}")

    def run_gap_repair(self) -> None:
        """Run pending gap repairs."""
        self._log_event("GAP_REPAIR", "STARTED", "pending")
        try:
            result = repair_pending_gaps(
                db=self._db,
                provider=self._provider,
                local_cache_dir=str(self._config.local_data_cache_dir),
            )
        except Exception as exc:
            self._log_event("GAP_REPAIR", "FAILED", f"error={type(exc).__name__}:{exc}")
            raise
        self._log_event(
            "GAP_REPAIR",
            "COMPLETED",
            f"repaired={result.repaired_count},failed={result.failed_count}",
        )

    def run_training(self, *, cycle_kind: str = "SCHEDULED") -> None:
        """Run one training cycle with strict local-data gate."""
        if self._config.force_local_data_for_training and self._config.allow_provider_calls_during_training:
            raise RuntimeError("Invalid config: local-only training cannot allow provider calls")

        self._log_event("TRAINING", "STARTED", f"cycle_kind={cycle_kind}")
        try:
            training_result = run_training_cycle(
                db=self._db,
                symbols=self._symbols,
                local_cache_dir=self._config.local_data_cache_dir,
                output_root=Path("artifacts/model_bundles"),
                account_id=1,
                cost_profile_id=1,
                strategy_code_sha="0" * 40,
                config_hash=stable_hash(("phase6_config", self._config.training_universe_version, cycle_kind)),
                universe_hash=stable_hash(("phase6_universe", *self._symbols)),
                random_seed=7,
                cycle_kind=cycle_kind,
            )
        except Exception as exc:
            self._log_event("TRAINING", "FAILED", f"cycle_kind={cycle_kind},error={type(exc).__name__}:{exc}")
            raise

        self._log_event(
            "TRAINING",
            "COMPLETED" if training_result.approved else "REJECTED",
            f"cycle_id={training_result.training_cycle_id},reason={training_result.reason_code},cycle_kind={cycle_kind}",
        )

    def _scheduled_training_already_ran_today(self, now_utc: datetime) -> bool:
        day_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        row = self._db.fetch_one(
            """
            SELECT COUNT(*) AS n
            FROM training_cycle
            WHERE cycle_kind = 'SCHEDULED'
              AND started_at_utc >= :day_start
              AND started_at_utc < :day_end
            """,
            {
                "day_start": day_start,
                "day_end": day_end,
            },
        )
        return int(row["n"]) > 0 if row is not None else False

    def _drift_retrain_recently_ran(self, now_utc: datetime) -> bool:
        window_start = now_utc - timedelta(minutes=self._config.drift_retrain_cooldown_minutes)
        row = self._db.fetch_one(
            """
            SELECT COUNT(*) AS n
            FROM training_cycle
            WHERE cycle_kind = 'DRIFT_TRIGGERED'
              AND started_at_utc >= :window_start
            """,
            {"window_start": window_start},
        )
        return int(row["n"]) > 0 if row is not None else False

    def _compute_feature_psi(self) -> Decimal:
        snapshot_rows = self._db.fetch_all(
            """
            SELECT dataset_snapshot_id
            FROM dataset_snapshot
            ORDER BY generated_at_utc DESC
            LIMIT 2
            """,
            {},
        )
        if len(snapshot_rows) < 2:
            return Decimal("0")

        latest_id = str(snapshot_rows[0]["dataset_snapshot_id"])
        prior_id = str(snapshot_rows[1]["dataset_snapshot_id"])
        component_rows = self._db.fetch_all(
            """
            SELECT dataset_snapshot_id, symbol, component_row_count
            FROM dataset_snapshot_component
            WHERE dataset_snapshot_id = ANY(:dataset_snapshot_ids)
            """,
            {"dataset_snapshot_ids": [latest_id, prior_id]},
        )

        latest_counts: dict[str, int] = {}
        prior_counts: dict[str, int] = {}
        for row in component_rows:
            snapshot_id = str(row["dataset_snapshot_id"])
            symbol = str(row["symbol"]).upper()
            count = int(row["component_row_count"])
            if snapshot_id == latest_id:
                latest_counts[symbol] = latest_counts.get(symbol, 0) + count
            elif snapshot_id == prior_id:
                prior_counts[symbol] = prior_counts.get(symbol, 0) + count

        latest_total = sum(latest_counts.values())
        prior_total = sum(prior_counts.values())
        if latest_total <= 0 or prior_total <= 0:
            return Decimal("0")

        symbols = set(latest_counts) | set(prior_counts)
        epsilon = 1e-9
        psi_value = 0.0
        for symbol in symbols:
            latest_share = max(float(latest_counts.get(symbol, 0)) / float(latest_total), epsilon)
            prior_share = max(float(prior_counts.get(symbol, 0)) / float(prior_total), epsilon)
            psi_value += (latest_share - prior_share) * math.log(latest_share / prior_share)

        return Decimal(str(max(0.0, psi_value)))

    def _compute_drift_observation(self, now_utc: datetime) -> DriftObservation:
        recent_start = now_utc - timedelta(hours=24)
        baseline_start = now_utc - timedelta(days=30)

        recent_row = self._db.fetch_one(
            """
            SELECT
                COUNT(*) AS sample_count,
                COALESCE(AVG(directional_accuracy), 0) AS avg_accuracy,
                COALESCE(AVG(ece), 0) AS avg_ece
            FROM hindcast_forecast_metric
            WHERE symbol = 'GLOBAL'
              AND horizon = 'H1'
              AND metric_kind = 'ROLLING'
              AND measured_at_utc >= :recent_start
            """,
            {"recent_start": recent_start},
        )
        baseline_row = self._db.fetch_one(
            """
            SELECT
                COUNT(*) AS sample_count,
                COALESCE(AVG(directional_accuracy), 0) AS avg_accuracy,
                COALESCE(AVG(ece), 0) AS avg_ece
            FROM hindcast_forecast_metric
            WHERE symbol = 'GLOBAL'
              AND horizon = 'H1'
              AND metric_kind = 'ROLLING'
              AND measured_at_utc >= :baseline_start
              AND measured_at_utc < :recent_start
            """,
            {
                "baseline_start": baseline_start,
                "recent_start": recent_start,
            },
        )

        recent_samples = int(recent_row["sample_count"]) if recent_row is not None else 0
        baseline_samples = int(baseline_row["sample_count"]) if baseline_row is not None else 0
        if recent_samples <= 0 or baseline_samples < self._config.drift_min_baseline_samples:
            return DriftObservation(
                symbol="GLOBAL",
                horizon="H1",
                accuracy_drop_pp=Decimal("0"),
                ece_delta=Decimal("0"),
                psi_value=Decimal("0"),
            )

        recent_acc = self._to_decimal(recent_row["avg_accuracy"])
        baseline_acc = self._to_decimal(baseline_row["avg_accuracy"])
        recent_ece = self._to_decimal(recent_row["avg_ece"])
        baseline_ece = self._to_decimal(baseline_row["avg_ece"])

        accuracy_drop_pp = max(Decimal("0"), (baseline_acc - recent_acc) * Decimal("100"))
        ece_delta = max(Decimal("0"), recent_ece - baseline_ece)
        psi_value = self._compute_feature_psi()

        return DriftObservation(
            symbol="GLOBAL",
            horizon="H1",
            accuracy_drop_pp=accuracy_drop_pp,
            ece_delta=ece_delta,
            psi_value=psi_value,
        )

    def maybe_trigger_drift_training(self) -> bool:
        """Evaluate drift and trigger retraining when thresholds are exceeded."""
        now_utc = self._clock.now_utc().astimezone(timezone.utc)
        thresholds = DriftThresholds(
            accuracy_drop_pp=Decimal(str(self._config.drift_accuracy_drop_pp)),
            ece_delta=Decimal(str(self._config.drift_ece_delta)),
            psi_threshold=Decimal(str(self._config.drift_psi_threshold)),
        )
        observation = self._compute_drift_observation(now_utc)
        triggered = persist_drift_event(
            self._db,
            training_cycle_ref=f"DRIFT_CHECK::{now_utc.replace(minute=0, second=0, microsecond=0).isoformat()}",
            observation=observation,
            thresholds=thresholds,
        )
        if not triggered:
            return False
        if self._drift_retrain_recently_ran(now_utc):
            self._log_event(
                "DRIFT_RETRAIN",
                "SKIPPED",
                f"cooldown_minutes={self._config.drift_retrain_cooldown_minutes}",
            )
            return False
        self.run_training(cycle_kind="DRIFT_TRIGGERED")
        return True

    @staticmethod
    def _extract_cycle_id(details: str | None) -> str | None:
        if not details:
            return None
        marker = "cycle_id="
        idx = details.find(marker)
        if idx < 0:
            return None
        value = details[idx + len(marker) :]
        if "," in value:
            value = value.split(",", 1)[0]
        return value.strip() or None

    def get_status(self) -> DaemonStatus:
        """Read current daemon status payload."""
        ingestion_row = self._db.fetch_one(
            """
            SELECT ingestion_cycle_id
            FROM ingestion_cycle
            ORDER BY started_at_utc DESC
            LIMIT 1
            """,
            {},
        )
        training_run_row = self._db.fetch_one(
            """
            SELECT
                tc.training_cycle_id,
                CASE WHEN mtr.approved THEN 'COMPLETED' ELSE 'REJECTED' END AS status
            FROM model_training_run mtr
            JOIN training_cycle tc
              ON tc.training_cycle_id = mtr.training_cycle_id
            ORDER BY tc.started_at_utc DESC
            LIMIT 1
            """,
            {},
        )
        training_event_row = self._db.fetch_one(
            """
            SELECT status, details
            FROM automation_event_log
            WHERE event_type = 'TRAINING'
            ORDER BY event_ts_utc DESC
            LIMIT 1
            """,
            {},
        )
        if training_run_row is not None:
            training_cycle_id = str(training_run_row["training_cycle_id"])
            training_status = str(training_run_row["status"])
        elif training_event_row is not None:
            training_cycle_id = self._extract_cycle_id(str(training_event_row.get("details", "")))
            training_status = str(training_event_row["status"])
        else:
            training_cycle_id = None
            training_status = None

        return DaemonStatus(
            bootstrap_complete=self.bootstrap_complete(),
            universe_symbol_count=len(self._symbols),
            last_ingestion_cycle_id=None if ingestion_row is None else str(ingestion_row["ingestion_cycle_id"]),
            last_training_cycle_id=training_cycle_id,
            last_training_status=training_status,
        )

    def _run_once_cycle(self) -> None:
        if self._config.enable_continuous_ingestion:
            self.run_incremental_sync()
        self.run_gap_repair()

        if not self.bootstrap_complete() or not self._config.enable_autonomous_retraining:
            return

        now_utc = self._clock.now_utc().astimezone(timezone.utc)
        if now_utc.hour == self._config.retrain_hour_utc:
            if self._scheduled_training_already_ran_today(now_utc):
                self._log_event("TRAINING_SCHEDULED", "SKIPPED", f"already_ran_for_date={now_utc.date().isoformat()}")
            else:
                self.run_training(cycle_kind="SCHEDULED")
            return
        self.maybe_trigger_drift_training()

    def run_once(self) -> None:
        """Execute one full daemon loop iteration."""
        self.acquire_exclusive_lock()
        try:
            self._run_once_cycle()
            self._refresh_lock_heartbeat()
        finally:
            self.release_exclusive_lock()

    def daemon_loop(self, *, max_cycles: int | None = None) -> None:
        """Run autonomous loop until interrupted or max_cycles reached."""
        self.acquire_exclusive_lock()
        self._safe_log_event("DAEMON", "STARTED", f"max_cycles={max_cycles if max_cycles is not None else 'infinite'}")
        cycles = 0
        consecutive_failures = 0
        try:
            while True:
                try:
                    self._run_once_cycle()
                    self._refresh_lock_heartbeat()
                    consecutive_failures = 0
                except Exception as exc:
                    consecutive_failures += 1
                    self._safe_log_event(
                        "DAEMON_CYCLE",
                        "FAILED",
                        f"failure_count={consecutive_failures},error={type(exc).__name__}:{exc}",
                    )
                    if consecutive_failures >= self._config.daemon_max_consecutive_failures:
                        raise RuntimeError(
                            f"Phase 6 daemon exceeded max consecutive failures ({self._config.daemon_max_consecutive_failures})"
                        ) from exc
                    time.sleep(self._config.daemon_failure_backoff_seconds)
                    continue

                cycles += 1
                if max_cycles is not None and cycles >= max_cycles:
                    return
                time.sleep(self._config.ingestion_loop_seconds)
        finally:
            self._safe_log_event("DAEMON", "STOPPED", f"completed_cycles={cycles}")
            self.release_exclusive_lock()
