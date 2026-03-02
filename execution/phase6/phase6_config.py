"""Environment-backed configuration for Phase 6 automation."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Phase6Config:
    """Canonical configuration surface for Phase 6A/6B runtime."""

    hist_market_data_provider: str
    hist_market_data_api_key: str
    hist_market_data_api_secret: str
    hist_market_data_base_url: str
    kraken_public_base_url: str
    universe_ranking_source: str
    universe_refresh_cron: str
    training_universe_version: str
    local_data_cache_dir: Path
    force_local_data_for_training: bool
    allow_provider_calls_during_training: bool
    enable_continuous_ingestion: bool
    enable_autonomous_retraining: bool
    ingestion_loop_seconds: int
    retrain_hour_utc: int
    api_budget_per_minute: int
    drift_accuracy_drop_pp: float
    drift_ece_delta: float
    drift_psi_threshold: float
    drift_retrain_cooldown_minutes: int
    drift_min_baseline_samples: int
    promotion_local_branch: str
    daemon_lock_stale_seconds: int
    daemon_failure_backoff_seconds: int
    daemon_max_consecutive_failures: int


_REQUIRED_KEYS: tuple[str, ...] = (
    "HIST_MARKET_DATA_PROVIDER",
    "HIST_MARKET_DATA_API_KEY",
    "HIST_MARKET_DATA_BASE_URL",
    "KRAKEN_PUBLIC_BASE_URL",
    "UNIVERSE_RANKING_SOURCE",
    "UNIVERSE_REFRESH_CRON",
    "TRAINING_UNIVERSE_VERSION",
    "LOCAL_DATA_CACHE_DIR",
)


def _read_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value.strip() == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def _read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"Invalid boolean value for {name}: {raw}")


def _read_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise RuntimeError(f"Invalid integer value for {name}: {raw}") from exc
    return value


def _read_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise RuntimeError(f"Invalid float value for {name}: {raw}") from exc
    return value


def load_phase6_config() -> Phase6Config:
    """Load and validate Phase 6 configuration from environment."""
    for key in _REQUIRED_KEYS:
        _read_env(key)

    provider = _read_env("HIST_MARKET_DATA_PROVIDER")
    if provider != "COINAPI":
        raise RuntimeError("Phase 6A source policy requires HIST_MARKET_DATA_PROVIDER=COINAPI")

    ranking_source = _read_env("UNIVERSE_RANKING_SOURCE")
    if ranking_source != "COINAPI":
        raise RuntimeError("Phase 6A source policy requires UNIVERSE_RANKING_SOURCE=COINAPI")

    return Phase6Config(
        hist_market_data_provider=provider,
        hist_market_data_api_key=_read_env("HIST_MARKET_DATA_API_KEY"),
        hist_market_data_api_secret=os.getenv("HIST_MARKET_DATA_API_SECRET", "").strip(),
        hist_market_data_base_url=_read_env("HIST_MARKET_DATA_BASE_URL"),
        kraken_public_base_url=_read_env("KRAKEN_PUBLIC_BASE_URL"),
        universe_ranking_source=ranking_source,
        universe_refresh_cron=_read_env("UNIVERSE_REFRESH_CRON"),
        training_universe_version=_read_env("TRAINING_UNIVERSE_VERSION"),
        local_data_cache_dir=Path(_read_env("LOCAL_DATA_CACHE_DIR")).resolve(),
        force_local_data_for_training=_read_bool("FORCE_LOCAL_DATA_FOR_TRAINING", True),
        allow_provider_calls_during_training=_read_bool("ALLOW_PROVIDER_CALLS_DURING_TRAINING", False),
        enable_continuous_ingestion=_read_bool("ENABLE_CONTINUOUS_INGESTION", True),
        enable_autonomous_retraining=_read_bool("ENABLE_AUTONOMOUS_RETRAINING", True),
        ingestion_loop_seconds=_read_int("PHASE6_INGESTION_LOOP_SECONDS", 60),
        retrain_hour_utc=_read_int("PHASE6_RETRAIN_HOUR_UTC", 0),
        api_budget_per_minute=_read_int("PHASE6_API_BUDGET_PER_MINUTE", 120),
        drift_accuracy_drop_pp=_read_float("PHASE6_DRIFT_ACCURACY_DROP_PP", 5.0),
        drift_ece_delta=_read_float("PHASE6_DRIFT_ECE_DELTA", 0.03),
        drift_psi_threshold=_read_float("PHASE6_DRIFT_PSI_THRESHOLD", 0.25),
        drift_retrain_cooldown_minutes=_read_int("PHASE6_DRIFT_RETRAIN_COOLDOWN_MINUTES", 360),
        drift_min_baseline_samples=_read_int("PHASE6_DRIFT_MIN_BASELINE_SAMPLES", 24),
        promotion_local_branch=os.getenv("PHASE6_PROMOTION_LOCAL_BRANCH", "automation/phase6-promotions").strip(),
        daemon_lock_stale_seconds=_read_int("PHASE6_DAEMON_LOCK_STALE_SECONDS", 900),
        daemon_failure_backoff_seconds=_read_int("PHASE6_DAEMON_FAILURE_BACKOFF_SECONDS", 120),
        daemon_max_consecutive_failures=_read_int("PHASE6_DAEMON_MAX_CONSECUTIVE_FAILURES", 10),
    )
