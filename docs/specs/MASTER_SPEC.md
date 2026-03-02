# AI CRYPTO TRADING SYSTEM
## MASTER TECHNICAL ARCHITECTURE & PRODUCTION SPECIFICATION
Version: 1.1
Status: AUTHORITATIVE

---

# 1. Executive Overview

This repository defines a production-grade deterministic quantitative crypto trading system.

System goals:

- continuous live prediction/evaluation/trading
- strict capital preservation
- adaptive campaign management (short and long lifecycle support)
- deterministic replay and audit

Current state:

- Phase 0-5 deterministic core, replay harness, governed risk runtime, deterministic order lifecycle engine, and deterministic portfolio/ledger runtime are completed.
- Phase 6A historical data foundation and continuous training bootstrap is the next active roadmap slice per `PROJECT_ROADMAP.md`.

Authoritative strategy logic:

- `docs/specs/TRADING_LOGIC_EXECUTION_SPEC.md`

---

# 2. Trading Environment & Core Constraints

- Venue: Kraken Spot
- Long-only (no margin, no borrowing, no leverage)
- Risk controls enforced pre-order
- All decision actions logged with reason codes

Exposure/position controls:

- Defaults exist, but values are profile-configurable.
- `max_total_exposure` and `max_cluster_exposure` must support:
  - percent-of-portfolio mode
  - absolute-amount mode

---

# 3. Data and Feature Contract

- Historical-only features (no leakage)
- Deterministic feature generation
- Timestamp integrity and replay compatibility
- Multi-scale features are allowed; no mandatory fixed holding window assumptions
- Full available market history must be ingested for the governed training universe.
- Incremental market-data sync must be continuous and deterministic.

---

# 4. Model Architecture

Required model families:

- tree models (XGBoost, LightGBM, Random Forest)
- sequence models (LSTM, Transformer)
- regime classifier
- meta-learner/ensemble combiner

Training/inference requirements:

- walk-forward validation
- reproducible model lineage
- drift-aware retraining policy
- per-coin specialist models plus global cross-asset models
- deterministic ensemble composition

---

# 5. Live Decision Framework

Decisioning is continuous and event-driven.

Decision triggers include:

- market data changes
- liquidity/order-book changes
- position and risk state changes
- liveness heartbeat fallback

No fixed global strategy update interval is required.

Forecast-horizon policy:

- model horizons may exist internally
- horizons are not mandatory holding-time limits
- runtime decisions are always based on latest prediction state

---

# 6. Strategy Behavior

Required behavior:

1. Prediction-led entry gating (avoid entering when near-term downside is likely).
2. Dip-aware entry behavior (enter after favorable drop-and-recovery setup when predicted).
3. Tactical profit realization (partial exits) during campaign life.
4. Tactical re-entry when local edge recovers.
5. Final exit when persistent negative outlook and weak rebound probability dominate.

Strategy must not rely on fixed timer exits or single loss-threshold-only exits.

---

# 7. Risk Management Framework

Risk policy is profile-driven with governed defaults.

Must support configurable:

- max concurrent positions
- total exposure mode/value
- cluster exposure mode/value
- strategy sensitivity and persistence controls

Portfolio drawdown controls remain mandatory for new-risk admission.

Existing positions must still be managed adaptively by prediction-led logic, including severe-loss recovery analysis.

---

# 8. Severe Loss Recovery Behavior

When an open position is deeply adverse:

- do not force panic liquidation solely on threshold breach
- continuously evaluate rebound-vs-continuation outlook
- choose hold / partial de-risk / full exit according to predicted persistence risk

This behavior is mandatory and documented in the trading logic spec.

---

# 9. Execution and Accounting

Execution must:

- apply active profile constraints deterministically
- enforce no-leverage and exposure rules
- log every action and rejection reason
- preserve append-only accounting and replay integrity

---

# 10. Replay and Determinism

The system must remain replay-authoritative:

- deterministic context loading
- deterministic strategy evaluation
- deterministic action emission
- complete traceability of model/profile inputs

---

# 11. Governance and Policy References

Primary governance documents:

- `docs/specs/PROJECT_GOVERNANCE.md`
- `docs/specs/RISK_RULES.md`
- `docs/specs/TRADING_LOGIC_EXECUTION_SPEC.md`
- `docs/specs/HISTORICAL_DATA_PROVIDER_AND_CONTINUOUS_TRAINING_SPEC.md`
- `docs/specs/OPERATOR_CONTROL_PLANE_AND_KRAKEN_ONBOARDING_SPEC.md`
- `docs/specs/LOCAL_FIRST_RUNTIME_AND_PRIVACY_SPEC.md`
- `docs/specs/MODEL_BUNDLE_DISTRIBUTION_AND_UPDATE_SPEC.md`
- `docs/specs/PRODUCTION_OPERATIONS_AND_RELIABILITY_SPEC.md`
- `docs/specs/SCHEMA_DDL_MASTER.md`
- `docs/specs/ARCHITECT_DECISIONS.md`

---

# 12. Planned Operator Frontend and Kraken Onboarding

Planned delivery scope includes a user-facing operator frontend and an easy, secure Kraken connection flow.

Required frontend product surfaces:

- governed profile/settings management
- runtime status and risk-gate visibility
- decision/prediction visibility with reason-code context
- holdings and per-asset chart visibility

Kraken onboarding requirements:

- guided API key setup with minimum required scopes
- explicit no-withdrawal key policy
- secure credential handling and connectivity validation
- paper-first default with explicit live enable confirmation

---

# 13. Planned Local-First Runtime and Model Bundle Lifecycle

Productization direction is local-first:

- end-user setup and operation must work fully on local machines
- mandatory cloud dependencies are prohibited for core runtime operation
- local runtime service + local control API are first-class architecture components

Model delivery/update direction:

- trained inference-ready model/data/algorithm artifacts are versioned in this GitHub repository and continuously updated
- users should not initialize from empty/untrained models on first install
- macOS app sync path retrieves governed artifacts from this repository
- model updates require compatibility checks, atomic swap, and rollback on failure

---

# 14. Historical Data and Continuous Training Policy

The platform must train from full available history, not short recent windows only.

Required policy:

- external historical-data provider integration is mandatory for deep-history backfill
- continuous incremental sync must append new market data deterministically
- training universe is versioned and governed (Universe V1 top-30 non-stable set)
- Universe V1 symbols: `BTC, ETH, BNB, XRP, SOL, TRX, ADA, BCH, XMR, LINK, XLM, HBAR, LTC, AVAX, ZEC, SUI, SHIB, TON, DOT, UNI, AAVE, TAO, NEAR, ETC, ICP, POL, KAS, ALGO, FIL, APT`
- retraining runs are scheduled and/or drift-triggered with promotion gates

Authoritative implementation contract:

- `docs/specs/HISTORICAL_DATA_PROVIDER_AND_CONTINUOUS_TRAINING_SPEC.md`

---

END OF MASTER SPECIFICATION
