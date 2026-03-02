# Quantitative Crypto Trading System
**Governed | Deterministic | Live Adaptive Trading**

---

## 1. Overview

This repository defines a deterministic quantitative crypto trading system for Kraken Spot markets.

Core intent:

- continuously predict, evaluate, and trade in live mode
- preserve capital with enforced runtime risk controls
- use adaptive campaign management instead of fixed hold timers
- support deterministic replay/audit for every decision

Implementation state tracking:

- Current phase-by-phase status is maintained in `AGENTS.md` and `docs/specs/PROJECT_ROADMAP.md`.
- This README intentionally describes the final production-grade system behavior and invariants.

---

## 2. Trading Method (High-Level)

The system does not depend on fixed time windows for entry/exit.

It behaves as a live campaign engine:

1. Continuously evaluate model outputs and trend context.
2. Avoid entry when predicted downside dominates.
3. Enter after favorable dip-and-recovery setups when predicted.
4. Harvest short-term profits via tactical partial exits/re-entries while campaign thesis remains valid.
5. Exit fully when outlook is strongly negative and recovery probability is low.

Severe-drop behavior:

- A large loss alone is not an automatic panic-sell trigger.
- The system continuously predicts rebound-vs-continuation and chooses hold, partial de-risk, or full exit accordingly.

---

## 3. Risk Controls and Configurability

No leverage constraints:

- no margin
- no borrowing
- long-only spot positions

User-configurable controls (with defaults):

- max concurrent positions (default `10`)
- max total exposure, selectable as:
  - percent of portfolio (default `20%`)
  - absolute amount (default profile amount)
- max cluster exposure, selectable as:
  - percent of portfolio (default `8%`)
  - absolute amount (default profile amount)

Profile values are versioned and logged for replay.

---

## 4. Continuous Live Runtime Policy

Target runtime behavior is event-driven and continuous.

Decision triggers include:

- market updates
- liquidity/order-book changes
- position/risk state changes
- liveness heartbeat fallback

No fixed global update interval is required for strategy behavior.

---

## 5. Model Stack

Required predictive stack:

- XGBoost, LightGBM, Random Forest
- LSTM, Transformer
- Regime classifier
- Meta-learner/ensemble combiner

Training policy:

- walk-forward validation
- leakage prevention
- drift-aware retraining
- reproducible lineage

---

## 6. Determinism and Replay

All live decisions must remain deterministic and replay-reconstructable from stored state.

Phase 0-2 replay tooling remains authoritative for deterministic validation.

---

## 7. Governance Documents

Primary implementation references:

- `docs/specs/TRADING_LOGIC_EXECUTION_SPEC.md`
- `docs/specs/PROJECT_GOVERNANCE.md`
- `docs/specs/RISK_RULES.md`
- `docs/specs/SCHEMA_DDL_MASTER.md`
- `docs/specs/MASTER_SPEC.md`
- `docs/specs/PROJECT_ROADMAP.md`
- `docs/specs/ARCHITECT_DECISIONS.md`

Developers should implement strategy/risk behavior directly from these specs.

---

## 8. LLM Support Roadmap

Current order authority is quantitative-model driven.

Future LLM support may be added as advisory/context assistance, with governance approval required before any order-authoritative LLM mode.

---

END OF README
