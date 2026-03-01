# AI CRYPTO TRADING SYSTEM
## TRADING LOGIC AND EXECUTION SPECIFICATION
Version: 1.1
Status: AUTHORITATIVE (STRATEGY/DECISION LAYER)
Scope: Live Decisioning, Position Lifecycle, Adaptive Exit and Recovery Logic

---

# 0. Purpose

This document defines the complete trading logic developers must implement.

System intent:

1. Operate as a fully live, continuously evaluating trading system.
2. Use predictions and trend diagnostics, not fixed timer exits.
3. Support both short-term and long-term position lifecycles.
4. Allow user-adjustable risk/strategy parameters through the product interface.
5. Preserve deterministic audit/replay behavior.

This specification is binding with:

- `docs/specs/PROJECT_GOVERNANCE.md`
- `docs/specs/RISK_RULES.md`
- `docs/specs/SCHEMA_DDL_MASTER.md`

---

# 1. Phase Alignment and Compatibility

1. Phase 0-2 provides deterministic data/replay scaffolding.
2. This strategy spec defines what to implement in later runtime strategy phases.
3. Current hourly schema scaffolding is a historical/core contract; target live runtime behavior is continuous evaluation.
4. Any schema/runtime upgrades required for live continuous operation must be implemented via governed migration, not ad-hoc changes.

---

# 2. Core Trading Philosophy

The system is a live adaptive campaign engine.

Definitions:

- Campaign: full lifecycle from initial entry to final flat exit.
- Tactical realization: partial sell/re-entry actions that harvest short-term profit during campaign life.
- Final exit: complete campaign close when downside is strongly persistent and rebound odds are weak.

Required behavior:

1. Do not passively wait for a fixed "predicted quit time".
2. Keep evaluating while market data changes.
3. Harvest tactical opportunities while the broader thesis remains valid.
4. Exit quickly when outlook becomes strongly negative with low recovery probability.

---

# 3. Live Continuous Decision Model

## 3.1 Event-Driven Runtime

Runtime is continuous and event-driven.

Decision triggers include:

- Market data updates
- Order-book/liquidity shifts
- Position PnL state transitions
- Risk state transitions
- Fallback heartbeat for liveness

No fixed global decision interval is required for strategy logic.

## 3.2 Forecast Window Policy

No mandatory fixed forecast window is required for trading decisions.

- Models may internally use multi-horizon forecasts.
- Forecast horizons are model internals, not mandatory holding-time limits.
- Runtime decisions are based on latest prediction state and trend context.

---

# 4. User-Configurable Controls (Interface-Adjustable)

All numeric controls below must be user-configurable in UI with defaults.

## 4.1 Position/Exposure Controls

- `max_concurrent_positions` (default: `10`)
- `max_total_exposure` with mode:
  - `PERCENT_OF_PV` (default: `20%`)
  - `ABSOLUTE_AMOUNT` (default amount from profile)
- `max_cluster_exposure` with mode:
  - `PERCENT_OF_PV` (default: `8%`)
  - `ABSOLUTE_AMOUNT` (default amount from profile)

## 4.2 Strategy Sensitivity Controls

UI-adjustable profile parameters must include:

- Entry aggressiveness
- Re-entry aggressiveness
- Exit aggressiveness
- Recovery patience after severe drawdown
- Tactical profit-realization intensity
- Signal persistence requirements

## 4.3 Risk Tier Profile Controls

Drawdown/risk tiers must be configurable profiles with safe defaults.

- Defaults should mirror current governance defaults.
- Users may tune profiles within safety bounds defined by governance.

All profile changes must be versioned and logged.

---

# 5. Model and Signal Stack

Required predictive components:

- Tree models (XGBoost/LightGBM/Random Forest)
- Sequence models (LSTM/Transformer)
- Regime classifier
- Meta-learner or equivalent ensemble combiner

Training policy:

1. Continuous or scheduled retraining with drift monitoring.
2. Strict historical-only feature construction.
3. Walk-forward style validation remains mandatory.
4. Model and profile versions are first-class runtime inputs.

---

# 6. Decision Semantics (No Hardcoded Fixed Numbers)

The strategy runtime must evaluate qualitative states computed from model outputs and calibrated thresholds from the active profile.

State classes:

- `STRONG_POSITIVE`
- `POSITIVE`
- `NEUTRAL`
- `NEGATIVE`
- `STRONG_NEGATIVE`

Additional diagnostics:

- Rebound potential
- Persistent downside risk
- Volatility/liquidity risk context
- Regime confidence

All cutoffs and persistence counters are profile-driven, not hardcoded constants.

---

# 7. Entry Logic (Trend and Dip-Aware)

Entry must satisfy all:

1. Upside state is sufficiently positive by active profile.
2. Risk/capital/exposure constraints pass.
3. Liquidity/spread conditions pass.

Required dip-aware behavior:

- If model predicts near-term drop risk, do not enter early.
- Wait for improved entry condition after drop.
- If price has dropped and rebound probability becomes favorable, allow entry.

This explicitly supports "wait for drop, then buy when recovery outlook is favorable" behavior.

---

# 8. Open Position Management (Active Profit Collection)

Required behavior for each open campaign:

1. Continuously re-score campaign state.
2. If short-term edge weakens but broader thesis remains positive, execute tactical partial profit realization.
3. If local edge recovers and constraints allow, permit tactical re-entry.
4. Keep campaign alive while recovery/uptrend probability remains acceptable.

Partial realization and re-entry sizing must be profile-driven and deterministic.

---

# 9. Exit Logic (Prediction-Led, Not Loss-Threshold-Led)

Exit decisions must be prediction-led:

1. Exit immediately when outlook is strongly negative and recovery probability is low.
2. If outlook is uncertain, prefer controlled de-risking over forced full liquidation.
3. If rebound potential remains meaningful, avoid panic selling solely due to large drawdown.

Hard rule:

- Loss percentage alone must never be the sole liquidation trigger.

---

# 10. Severe Drop Recovery Protocol

When a position suffers a major adverse move:

1. Trigger recovery analysis mode.
2. Recompute rebound-vs-continuation outlook on each decision trigger.
3. Choose one of:
   - Continue hold (if rebound odds acceptable)
   - Partial de-risk (if mixed outlook)
   - Full exit (if downside persistence is strongly likely)

The system must be biased to avoid unnecessary low-point liquidation while still cutting risk when outlook is clearly poor.

---

# 11. Portfolio Drawdown and Entry Circuit Breaker

Portfolio-level drawdown controls remain mandatory, but behavior is policy-driven:

1. Drawdown controls primarily gate new risk admission.
2. Existing open positions continue to follow adaptive prediction-led management.
3. Portfolio drawdown does not imply automatic blanket liquidation of all open positions.

Default profile may include a 20% new-entry circuit breaker, but profile values are configurable per governance policy.

---

# 12. LLM Support Policy

Current production decision authority remains quantitative model-driven.

Future LLM support may be added in controlled modes:

- Advisory/context layer (allowed when enabled)
- Non-authoritative suggestion layer
- No direct autonomous order authority unless explicitly approved by governance and audited

Any LLM-assisted mode must be versioned, logged, and replay-compatible.

---

# 13. Required Runtime Procedure

For each decision trigger:

1. Load latest deterministic context (positions, risk, market state, model outputs, profile).
2. Evaluate entry/hold/partial/exit state classification.
3. Enforce exposure and risk limits using selected unit mode (percent or amount).
4. Emit deterministic action with reason codes.
5. Persist decision evidence for replay and audit.

---

# 14. Determinism and Audit Requirements

1. Every decision must include reason codes tied to current model/profile state.
2. Every profile parameter used must be logged with version identity.
3. Continuous runtime must still produce replay-reconstructable decision history.
4. No opaque discretionary behavior is allowed.

---

# 15. Implementation Acceptance Criteria

Implementation is compliant only when:

1. It runs continuously in live mode and evaluates on trigger events.
2. It supports configurable exposure units (percent/amount) and configurable position limits.
3. It uses prediction-led exits, not fixed loss-threshold-only exits.
4. It supports tactical profit collection before final campaign exit.
5. It preserves deterministic replay and governance traceability.

---

END OF TRADING LOGIC AND EXECUTION SPECIFICATION
