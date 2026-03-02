# AI CRYPTO TRADING SYSTEM
## HISTORICAL DATA PROVIDER AND CONTINUOUS TRAINING SPECIFICATION
Version: 1.0
Status: AUTHORITATIVE (PHASE 6A/6B DELIVERY CONTRACT)
Scope: Historical Data Backfill, Continuous Data Sync, Multi-Model Retraining Lifecycle

---

# 0. Purpose

Define mandatory standards for:

1. Acquiring full available market history for the supported trading universe.
2. Continuously ingesting new market data as it is published.
3. Training and continuously retraining per-coin and global models from governed data lineage.

This spec is binding with:

- `docs/specs/PROJECT_ROADMAP.md`
- `docs/specs/PROJECT_GOVERNANCE.md`
- `docs/specs/MASTER_SPEC.md`
- `docs/specs/TRADING_LOGIC_EXECUTION_SPEC.md`
- `docs/specs/MODEL_BUNDLE_DISTRIBUTION_AND_UPDATE_SPEC.md`

---

# 1. Non-Negotiable Outcomes

1. Training pipelines must use the full available historical record for each supported coin from the earliest provider-available timestamp through present.
2. Incremental ingestion must continuously append newly published market data.
3. Data lineage and model lineage must be deterministic and replay-auditable.
4. Retraining must run continuously (scheduled and/or drift-triggered) with governed promotion gates.
5. No model can be promoted to runtime authority unless validation gates pass.

---

# 2. External Data Provider Contract

## 2.1 Source Strategy

Phase 6A must implement dual-source ingestion roles:

1. Canonical historical provider adapter:
   - Required for deep history backfill.
   - Must support historical bars/trades depth sufficient for multi-year walk-forward training.
2. Kraken public market-data adapter:
   - Required for venue-aligned reconciliation and recent continuity checks.
   - Private Kraken keys are not required for Phase 6A historical ingestion.

Provider adapter design must be pluggable (no hardcoded vendor lock in core training pipeline).

Default implementation recommendation (v1):

1. Primary historical provider: `COINAPI` (deep-history OHLCV/trades ingestion path).
2. Universe/market-cap metadata provider: `COINGECKO` (universe maintenance and ranking metadata).
3. Venue parity source: `KRAKEN_PUBLIC` (pair/symbol and venue-aligned continuity checks).

## 2.2 Key/Secret Readiness Requirements

Phase 6A implementation must support:

- `HIST_MARKET_DATA_PROVIDER` (provider identifier)
- `HIST_MARKET_DATA_API_KEY` (required when provider requires auth)
- `HIST_MARKET_DATA_API_SECRET` (optional, provider-dependent)
- `HIST_MARKET_DATA_BASE_URL` (optional override)

Kraken private trading credentials:

- `KRAKEN_API_KEY`
- `KRAKEN_API_SECRET`

remain optional for Phase 6A and become mandatory only for live/paper exchange account operations in later phases.

## 2.3.1 Provider Onboarding Variables (Required .env Surface)

`.env` must define at minimum:

- `HIST_MARKET_DATA_PROVIDER` (`COINAPI` for default Phase 6A implementation)
- `HIST_MARKET_DATA_API_KEY`
- `HIST_MARKET_DATA_API_SECRET` (blank when provider does not require)
- `HIST_MARKET_DATA_BASE_URL`
- `UNIVERSE_SOURCE_PROVIDER` (`COINGECKO`)
- `UNIVERSE_SOURCE_API_KEY` (provider tier dependent)
- `UNIVERSE_REFRESH_CRON` (for ranking refresh cadence)
- `TRAINING_UNIVERSE_VERSION` (default `UNIVERSE_V1_TOP30_NON_STABLE`)
- `ENABLE_CONTINUOUS_INGESTION` (`true`)
- `ENABLE_AUTONOMOUS_RETRAINING` (`true`)

Kraken private key variables:

- `KRAKEN_API_KEY`
- `KRAKEN_API_SECRET`

must be absent or unused in Phase 6A training-only environments unless explicit paper/live exchange testing is underway.

## 2.4 Data Integrity Requirements

Ingestion must enforce:

1. UTC timestamp normalization.
2. Deterministic deduplication (stable natural keys per symbol/timestamp/source granularity).
3. Gap detection and explicit backfill retry.
4. Zero silent data repair. Any correction must be versioned and auditable.

---

# 3. Historical Backfill and Continuous Sync Lifecycle

Phase 6A data lifecycle must implement:

1. Bootstrap backfill:
   - Full available history for every supported symbol.
   - Replay-safe append-only raw ingest records.
2. Incremental sync:
   - Scheduled polling and/or streaming append for new data.
   - Idempotent upsert semantics on raw-ingest staging keys.
3. Late-arrival reconciliation:
   - Detect and fill delayed candles/trades.
   - Preserve deterministic correction logs.
4. Dataset materialization:
   - Build training-ready canonical datasets from raw ingest with reproducible transforms.
   - Emit deterministic dataset hash artifacts.

---

# 4. Training Universe Policy (Versioned)

## 4.1 Universe V1 (Top 30 Non-Stable, Market-Cap Prioritized)

Initial required training universe is fixed as `UNIVERSE_V1_TOP30_NON_STABLE`:

1. BTC (Kraken symbol mapping: XBT)
2. ETH
3. BNB
4. XRP
5. SOL
6. TRX
7. ADA
8. BCH
9. XMR
10. LINK
11. XLM
12. HBAR
13. LTC
14. AVAX
15. ZEC
16. SUI
17. SHIB
18. TON
19. DOT
20. UNI
21. AAVE
22. TAO
23. NEAR
24. ETC
25. ICP
26. POL
27. KAS
28. ALGO
29. FIL
30. APT

Universe constraints:

- Stablecoins and tokenized fiat assets are excluded from this training universe.
- Wrapped/staked synthetic wrappers are excluded from this training universe.
- Universe changes require versioned governance updates (`UNIVERSE_V2+`) and migration notes in roadmap/spec artifacts.

## 4.2 Quote-Currency Coverage

Data and feature pipelines must support quote-currency surfaces required by runtime policy:

- `CAD`
- `USD`
- `USDC`

---

# 5. Model Topology Requirements

Training architecture must include:

1. Per-coin specialist models (for each symbol in Universe V1).
2. Global cross-asset models (systemic regime/risk pattern capture).
3. Ensemble layer combining specialist and global signals into deterministic decision inputs.

Required model-family coverage remains:

- tree models (XGBoost, LightGBM, Random Forest)
- sequence models (LSTM, Transformer)
- regime classifier
- meta-learner/ensemble combiner

## 5.1 Optimization Objective (Accuracy and Intelligence Target)

Training must maximize out-of-sample predictive quality and decision utility while preserving determinism:

1. Directional accuracy on governed horizons.
2. Calibrated probability quality (not just raw classification accuracy).
3. Risk-adjusted trading utility in deterministic simulation.
4. Stability under regime shifts (degradation controls and drift detection).

Mandatory anti-overfit rule:

- No model promotion can be justified by in-sample metrics only.

## 5.2 Per-Model Training Method Contract

### 5.2.1 Tree Specialists (XGBoost, LightGBM, Random Forest)

Must implement:

1. Per-coin specialist training for each Universe V1 symbol.
2. Leakage-safe feature snapshots with walk-forward fold segmentation.
3. Multi-horizon supervised targets (direction + return magnitude categories/values).
4. Post-training probability calibration (Platt/isotonic or governed equivalent).
5. Deterministic hyperparameter search with reproducible seeds and lineage logging.

### 5.2.2 Sequence Specialists (LSTM, Transformer)

Must implement:

1. Causal sequence inputs only (no future leakage).
2. Multi-resolution temporal windows (short/medium/long context).
3. Multi-task outputs for directional probability, expected move, and risk context.
4. Early stopping and regularization governed by walk-forward OOS metrics.
5. Deterministic training artifacts (seed, config hash, dataset hash).

### 5.2.3 Regime Classifier

Must implement:

1. Global cross-asset regime classification (trend/range/high-vol/stress states).
2. Deterministic posterior outputs consumed by specialist-model gating.
3. Explicit false-regime transition penalties in validation scoring.

### 5.2.4 Meta-Learner / Ensemble Combiner

Must implement:

1. Leakage-safe stacking using out-of-fold base-model predictions only.
2. Deterministic combination weights and confidence outputs.
3. Promotion criteria based on both forecast quality and deterministic strategy utility.

## 5.3 Hindcast + Forecast Quality Tests

Required predictive-evidence tests include:

1. Hindcast check:
   - Using data up to `T-2d`, generate prediction for `T-1d`, then compare to realized `T-1d`.
2. Forward check:
   - Using data up to `T`, predict `T+1` (and configured future horizons), then score against realized outcomes when available.
3. Rolling evaluation:
   - Recompute hindcast/forecast metrics continuously across walk-forward windows.

---

# 6. Continuous Retraining and Promotion Policy

Retraining orchestration must support both:

1. Scheduled retraining cadence.
2. Drift-triggered retraining.

Each retraining run must produce:

- dataset hash and lineage metadata
- training window/fold metadata
- metric package
- model artifact set
- promotion decision evidence

Promotion gates are mandatory:

1. Walk-forward/OOS quality thresholds.
2. Deterministic simulation checks.
3. Risk-rule compliance checks.
4. Replay/audit artifact completeness.

Failed promotion leaves prior active model set unchanged.

## 6.1 Autonomous Runtime and Human Oversight Cadence

Training/ingestion operations must be autonomous by default:

1. Ingestion jobs run continuously.
2. Retraining jobs run on schedule and/or drift trigger.
3. Promotion checks run automatically after each candidate training cycle.

Human operator responsibilities remain mandatory:

1. Review model/report dashboards on governed cadence (daily/weekly as configured).
2. Approve policy changes (universe expansion, threshold changes, provider change).
3. Triage and resolve pipeline failures (data gaps, validation failures, drift breaches).

The intended operating mode is not manual constant intervention; it is autonomous operation with governed periodic supervision.

---

# 7. Phase Acceptance Criteria

Phase 6A is compliant only when:

1. Full available historical backfill is complete for all 30 universe symbols.
2. Incremental sync is automated and produces deterministic append logs.
3. Data quality checks (gaps, duplicates, ordering, schema validity) are continuously enforced.
4. Per-coin + global training pipelines can run end-to-end from canonical datasets.
5. Retraining and promotion decisions are reproducible and auditable.

Phase 6B (Backtest Orchestrator) is compliant only when:

1. Walk-forward training and validation run for all supported symbols.
2. Deterministic inference simulation uses Phase 6A governed datasets.
3. Fold metrics and lineage artifacts are fully persisted.

---

# 8. Test and Validation Requirements

Required test surfaces include:

1. Provider adapter contract tests (pagination, retry, rate-limit handling, deterministic normalization).
2. Backfill completeness tests per symbol/time range.
3. Incremental sync idempotency and late-arrival reconciliation tests.
4. Dataset-hash reproducibility tests.
5. Multi-model training orchestration tests (per-coin + global + ensemble).
6. Promotion gate tests (pass/fail behavior with deterministic reason codes).

---

# 9. Security and Privacy Requirements

1. API keys/secrets must never be committed to repo.
2. Secrets must not appear in logs, traces, crash dumps, or test artifacts.
3. Local-first secret handling remains governed by:
   - `docs/specs/LOCAL_FIRST_RUNTIME_AND_PRIVACY_SPEC.md`
4. Release bundle policy remains governed by:
   - `docs/specs/MODEL_BUNDLE_DISTRIBUTION_AND_UPDATE_SPEC.md`

---

END OF HISTORICAL DATA PROVIDER AND CONTINUOUS TRAINING SPECIFICATION
