from __future__ import annotations

import pytest

from execution.phase6.phase6_config import load_phase6_config


_REQUIRED_ENV = {
    "HIST_MARKET_DATA_PROVIDER": "COINAPI",
    "HIST_MARKET_DATA_API_KEY": "k",
    "HIST_MARKET_DATA_BASE_URL": "https://rest.coinapi.io",
    "KRAKEN_PUBLIC_BASE_URL": "https://api.kraken.com",
    "UNIVERSE_RANKING_SOURCE": "COINAPI",
    "UNIVERSE_REFRESH_CRON": "0 0 * * *",
    "TRAINING_UNIVERSE_VERSION": "UNIVERSE_V1_TOP30_NON_STABLE",
    "LOCAL_DATA_CACHE_DIR": "./data/market_archive",
}



def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)



def test_load_phase6_config_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FORCE_LOCAL_DATA_FOR_TRAINING", "true")
    monkeypatch.setenv("ALLOW_PROVIDER_CALLS_DURING_TRAINING", "false")
    monkeypatch.setenv("ENABLE_CONTINUOUS_INGESTION", "true")
    monkeypatch.setenv("ENABLE_AUTONOMOUS_RETRAINING", "true")
    monkeypatch.setenv("PHASE6_INGESTION_LOOP_SECONDS", "60")

    cfg = load_phase6_config()
    assert cfg.hist_market_data_provider == "COINAPI"
    assert cfg.universe_ranking_source == "COINAPI"
    assert cfg.console_log_enabled is True
    assert cfg.ingestion_loop_seconds == 60
    assert cfg.bootstrap_lookback_days == 7000
    assert cfg.min_free_disk_gb == 5.0
    assert cfg.adaptive_trade_poll_zero_streak == 3
    assert cfg.adaptive_trade_poll_interval_minutes == 5
    assert cfg.force_local_data_for_training is True
    assert cfg.allow_provider_calls_during_training is False
    assert cfg.drift_retrain_cooldown_minutes == 360
    assert cfg.drift_min_baseline_samples == 24
    assert cfg.daemon_lock_stale_seconds == 900
    assert cfg.daemon_failure_backoff_seconds == 120
    assert cfg.daemon_max_consecutive_failures == 10



def test_load_phase6_config_rejects_policy_violations(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("HIST_MARKET_DATA_PROVIDER", "OTHER")
    with pytest.raises(RuntimeError, match="HIST_MARKET_DATA_PROVIDER=COINAPI"):
        load_phase6_config()

    monkeypatch.setenv("HIST_MARKET_DATA_PROVIDER", "COINAPI")
    monkeypatch.setenv("UNIVERSE_RANKING_SOURCE", "OTHER")
    with pytest.raises(RuntimeError, match="UNIVERSE_RANKING_SOURCE=COINAPI"):
        load_phase6_config()



def test_load_phase6_config_invalid_bool(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FORCE_LOCAL_DATA_FOR_TRAINING", "maybe")
    with pytest.raises(RuntimeError, match="Invalid boolean"):
        load_phase6_config()


def test_load_phase6_config_invalid_int_and_float(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("PHASE6_INGESTION_LOOP_SECONDS", "NaN")
    with pytest.raises(RuntimeError, match="Invalid integer"):
        load_phase6_config()

    _set_required_env(monkeypatch)
    monkeypatch.delenv("PHASE6_INGESTION_LOOP_SECONDS", raising=False)
    monkeypatch.setenv("PHASE6_DRIFT_PSI_THRESHOLD", "not-a-float")
    with pytest.raises(RuntimeError, match="Invalid float"):
        load_phase6_config()


def test_load_phase6_config_missing_required(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("LOCAL_DATA_CACHE_DIR", raising=False)
    with pytest.raises(RuntimeError, match="Missing required environment variable: LOCAL_DATA_CACHE_DIR"):
        load_phase6_config()


def test_load_phase6_config_boolean_defaults_and_false_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FORCE_LOCAL_DATA_FOR_TRAINING", "off")
    monkeypatch.setenv("ALLOW_PROVIDER_CALLS_DURING_TRAINING", "no")
    monkeypatch.setenv("ENABLE_CONTINUOUS_INGESTION", "0")
    monkeypatch.setenv("ENABLE_AUTONOMOUS_RETRAINING", "false")
    monkeypatch.setenv("PHASE6_CONSOLE_LOG_ENABLED", "off")
    monkeypatch.delenv("PHASE6_PROMOTION_LOCAL_BRANCH", raising=False)

    cfg = load_phase6_config()
    assert cfg.force_local_data_for_training is False
    assert cfg.allow_provider_calls_during_training is False
    assert cfg.enable_continuous_ingestion is False
    assert cfg.enable_autonomous_retraining is False
    assert cfg.console_log_enabled is False
    assert cfg.promotion_local_branch == "automation/phase6-promotions"


def test_load_phase6_config_parses_float_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("PHASE6_DRIFT_PSI_THRESHOLD", "0.5")
    cfg = load_phase6_config()
    assert cfg.drift_psi_threshold == 0.5
