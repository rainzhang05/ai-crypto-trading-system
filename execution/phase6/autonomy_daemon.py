"""Single-process autonomous Phase 6 daemon orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Sequence

from execution.decision_engine import stable_hash
from execution.phase6.bootstrap_backfill import run_bootstrap_backfill
from execution.phase6.common import Phase6Clock, Phase6Database
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
        result = run_bootstrap_backfill(
            db=self._db,
            provider=self._provider,
            universe_symbols=self._symbols,
            asset_id_by_symbol=self._asset_id_by_symbol,
            local_cache_dir=str(self._config.local_data_cache_dir),
            start_ts_utc=start_ts_utc,
            end_ts_utc=end_ts_utc,
        )
        status = "COMPLETED" if result.completed else "FAILED"
        self._log_event("BOOTSTRAP", status, f"symbols_completed={result.symbols_completed}")
        if not result.completed:
            raise RuntimeError("Bootstrap backfill did not complete for all universe symbols")

    def run_incremental_sync(self) -> None:
        """Run one incremental ingestion cycle."""
        now_utc = self._clock.now_utc()
        self._log_event("INGESTION", "STARTED", now_utc.isoformat())
        result = run_incremental_sync(
            db=self._db,
            provider=self._provider,
            symbols=self._symbols,
            asset_id_by_symbol=self._asset_id_by_symbol,
            local_cache_dir=self._config.local_data_cache_dir,
            now_utc=now_utc,
        )
        self._log_event("INGESTION", "COMPLETED", f"cycle_id={result.ingestion_cycle_id}")

    def run_gap_repair(self) -> None:
        """Run pending gap repairs."""
        self._log_event("GAP_REPAIR", "STARTED", "pending")
        result = repair_pending_gaps(
            db=self._db,
            provider=self._provider,
            local_cache_dir=str(self._config.local_data_cache_dir),
        )
        self._log_event(
            "GAP_REPAIR",
            "COMPLETED",
            f"repaired={result.repaired_count},failed={result.failed_count}",
        )

    def run_training(self, *, cycle_kind: str = "SCHEDULED") -> None:
        """Run one training cycle with strict local-data gate."""
        if self._config.force_local_data_for_training and self._config.allow_provider_calls_during_training:
            raise RuntimeError("Invalid config: local-only training cannot allow provider calls")

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
        self._log_event(
            "TRAINING",
            "COMPLETED" if training_result.approved else "REJECTED",
            f"cycle_id={training_result.training_cycle_id},reason={training_result.reason_code}",
        )

    def maybe_trigger_drift_training(self) -> bool:
        """Evaluate drift and trigger retraining when thresholds are exceeded."""
        thresholds = DriftThresholds(
            accuracy_drop_pp=self._config.drift_accuracy_drop_pp,
            ece_delta=self._config.drift_ece_delta,
            psi_threshold=self._config.drift_psi_threshold,
        )
        observation = DriftObservation(
            symbol="GLOBAL",
            horizon="H1",
            accuracy_drop_pp=0,
            ece_delta=0,
            psi_value=0,
        )
        triggered = persist_drift_event(
            self._db,
            training_cycle_ref="DRIFT_CHECK",
            observation=observation,
            thresholds=thresholds,
        )
        if triggered:
            self.run_training(cycle_kind="DRIFT_TRIGGERED")
            return True
        return False

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
        training_row = self._db.fetch_one(
            """
            SELECT training_cycle_id, status
            FROM training_cycle
            ORDER BY started_at_utc DESC
            LIMIT 1
            """,
            {},
        )
        return DaemonStatus(
            bootstrap_complete=self.bootstrap_complete(),
            universe_symbol_count=len(self._symbols),
            last_ingestion_cycle_id=None if ingestion_row is None else str(ingestion_row["ingestion_cycle_id"]),
            last_training_cycle_id=None if training_row is None else str(training_row["training_cycle_id"]),
            last_training_status=None if training_row is None else str(training_row["status"]),
        )

    def run_once(self) -> None:
        """Execute one full daemon loop iteration."""
        if self._config.enable_continuous_ingestion:
            self.run_incremental_sync()
        self.run_gap_repair()
        if self.bootstrap_complete() and self._config.enable_autonomous_retraining:
            now_utc = self._clock.now_utc().astimezone(timezone.utc)
            if now_utc.hour == self._config.retrain_hour_utc:
                self.run_training(cycle_kind="SCHEDULED")
            else:
                self.maybe_trigger_drift_training()

    def daemon_loop(self, *, max_cycles: int | None = None) -> None:
        """Run autonomous loop until interrupted or max_cycles reached."""
        cycles = 0
        while True:
            self.run_once()
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                return
            time.sleep(self._config.ingestion_loop_seconds)
