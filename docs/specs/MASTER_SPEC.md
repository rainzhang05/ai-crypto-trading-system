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

- Phase 0-3 deterministic core, replay harness, and governed risk runtime are completed.
- Phase 4 order lifecycle implementation is ready to begin per `PROJECT_ROADMAP.md`.

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
- `docs/specs/SCHEMA_DDL_MASTER.md`
- `docs/specs/ARCHITECT_DECISIONS.md`

---

END OF MASTER SPECIFICATION
