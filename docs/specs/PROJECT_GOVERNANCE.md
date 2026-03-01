# AI CRYPTO TRADING SYSTEM
## PROJECT GOVERNANCE DOCUMENT
Version: 1.1
Status: AUTHORITATIVE

This document defines non-negotiable governance rules for architecture, finance, and operations.

Authoritative strategy behavior is defined in:

- `docs/specs/TRADING_LOGIC_EXECUTION_SPEC.md`

---

# 1. GOVERNING PRINCIPLES

1. Determinism is required.
2. All decisions must be backtestable and replayable.
3. Capital preservation has priority over raw return.
4. No hidden leverage, margin, or borrowing is allowed.
5. Risk controls must be enforced at execution time.
6. Strategy must be prediction-led, not fixed-rule-only.

---

# 2. ARCHITECTURE IMMUTABILITY WITH CONFIGURABILITY

The following domains require Architect approval for structural change:

- data lineage and replay contracts
- walk-forward validation structure
- fee/slippage and accounting logic
- risk-gating flow
- execution order lifecycle
- strategy state classification semantics

Configurable-at-runtime policy:

- Numeric strategy/risk values may be user-adjustable through governed profiles.
- Default values are baseline presets, not immutable constants.
- Profile changes must be versioned and logged.

---

# 3. DATA GOVERNANCE

1. No forward-looking leakage.
2. Timestamp integrity is mandatory.
3. Raw data must be preserved before transformation.
4. All feature pipelines must be reproducible.

---

# 4. MODEL GOVERNANCE

Models must:

- use walk-forward validation
- avoid static split misuse
- log training windows and parameters
- support drift-aware retraining
- remain reproducible

---

# 5. STRATEGY GOVERNANCE

Required:

1. Continuous live evaluation behavior (event-driven, not fixed timer-only strategy behavior).
2. Adaptive holding behavior (no universal forced max hold timer).
3. Tactical profit realization and re-entry behavior during campaigns.
4. Prediction-led exits with recovery-aware handling in severe adverse states.

Forbidden:

- hardcoding universal entry/exit thresholds directly in runtime logic without profile control
- timer-only liquidation behavior
- loss-percentage-only liquidation behavior

---

# 6. RISK GOVERNANCE

1. Position/exposure controls must be profile-configurable in UI.
2. `max_concurrent_positions`, `max_total_exposure`, and `max_cluster_exposure` must support governed defaults and user adjustment.
3. Total/cluster exposure must support both percent-of-PV mode and absolute-amount mode.
4. Portfolio drawdown controls gate new risk admission and must remain enforced.

---

# 7. EXECUTION GOVERNANCE

Execution engine must:

- validate active risk profile before order admission
- enforce capital and exposure constraints using selected unit mode
- log all order lifecycle events and reason codes
- preserve deterministic behavior for replay

---

# 8. LLM POLICY

Current order authority remains quantitative-model driven.

Future LLM support is allowed only as:

- advisory/context assistance
- non-authoritative suggestion layer

LLM can become order-authoritative only after explicit governance approval, auditing, and replay contract extension.

---

# 9. CHANGE MANAGEMENT

Any structural change requires:

1. Architect proposal
2. Implementation
3. Architect review
4. Auditor review
5. Decision log entry in `ARCHITECT_DECISIONS.md`

---

# 10. LOGGING REQUIREMENTS

System must log:

- model outputs and derived strategy states
- profile version and parameter values used for each decision
- entry/hold/partial/exit reason codes
- severe-loss recovery decisions
- risk gate outcomes

Logs must allow deterministic reconstruction.

---

# 11. PRODUCTION SAFETY REQUIREMENTS

Before live capital scaling:

- paper/live shadow validations
- risk/kill-switch drills
- replay parity checks
- profile governance checks

---

# 12. PRIORITY ORDER

When conflicts arise:

1. Capital Preservation
2. Deterministic Behavior
3. Risk Enforcement
4. Backtest/Replay Integrity
5. Optimization

---

END OF PROJECT GOVERNANCE DOCUMENT
