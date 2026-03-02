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
- As of 2026-03-02, implementation closure is complete through Phase 5; Phase 6A is the next roadmap slice.

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

Phase 6A data policy:

- full available historical data backfill for every governed training symbol
- continuous incremental data sync for newly published market data
- per-coin specialist models combined with global cross-asset models

Initial training universe (V1, top-30 non-stable):

`BTC, ETH, BNB, XRP, SOL, TRX, ADA, BCH, XMR, LINK, XLM, HBAR, LTC, AVAX, ZEC, SUI, SHIB, TON, DOT, UNI, AAVE, TAO, NEAR, ETC, ICP, POL, KAS, ALGO, FIL, APT`

Required preparation for Phase 6A:

- configure external historical market-data provider credentials (`HIST_MARKET_DATA_API_KEY`, provider-dependent secret/base URL as needed)
- Kraken private API keys are not required until paper/live exchange-credential phases
- copy `.env.example` to `.env` and populate provider credentials before running ingestion/training automation

---

## 6. Determinism and Replay

All live decisions must remain deterministic and replay-reconstructable from stored state.

Phase 0-5 replay/runtime validation gates remain authoritative for deterministic validation.

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
- `docs/specs/HISTORICAL_DATA_PROVIDER_AND_CONTINUOUS_TRAINING_SPEC.md`
- `docs/specs/OPERATOR_CONTROL_PLANE_AND_KRAKEN_ONBOARDING_SPEC.md`
- `docs/specs/LOCAL_FIRST_RUNTIME_AND_PRIVACY_SPEC.md`
- `docs/specs/MODEL_BUNDLE_DISTRIBUTION_AND_UPDATE_SPEC.md`
- `docs/specs/PRODUCTION_OPERATIONS_AND_RELIABILITY_SPEC.md`

Developers should implement strategy/risk behavior directly from these specs.

---

## 8. Planned User Frontend (Control Plane)

Planned first shipping product surface is a **local-first macOS desktop app** (SwiftUI) for operating the bot safely on user-owned hardware.

Required frontend capabilities:

- modify governed strategy/risk profile settings (within policy bounds)
- configure global exposure caps and per-quote-currency caps (`CAD`, `USD`, `USDC`)
- view current runtime status (mode, risk state, kill-switch status, health)
- inspect upcoming/active decision context and model predictions
- view current holdings, lots, and realized/unrealized PnL
- view per-asset charts (price, position, and decision overlays)
- view deterministic decision/action history with reason codes
- provide explicit risk warning + user confirmation before first live start

The frontend is planned as an operator control plane, not a risk bypass path.
All writes remain governed, versioned, and replay-auditable.

---

## 9. Planned Kraken Account Connection (Easy Path)

Planned onboarding includes the simplest safe path for users to connect their own Kraken account:

1. Guided connection wizard (paper first, then optional live enablement).
2. Step-by-step Kraken API key creation instructions with required permissions only.
3. Enforced no-withdrawal key policy and explicit scope validation checks.
4. One-time secure secret capture stored in macOS Keychain (never echoed in logs/UI after submission).
5. Connection health check + balance/permissions verification before enabling runtime.
6. Mandatory paper-trial completion gate before first live authorization.
7. Explicit final confirmation gate before live order authorization.

This onboarding flow will be treated as a first-class roadmap deliverable, not optional UX polish.

---

## 10. Local-First Runtime and Model Delivery

Product direction is local-first:

- core trading runtime must be fully operable on user machines without mandatory cloud dependency
- optional cloud services may be added later for backup/sync/update channels
- trained inference-ready model artifacts and metadata are distributed as signed GitHub Release bundles
- users receive one-click model updates with compatibility checks and rollback protection

Bundled distribution policy:

- users should not start from empty, untrained models on first install
- release bundles include inference artifacts and lineage metadata
- full raw training datasets are not required in default user bundles

---

## 11. LLM Support Roadmap

Current order authority is quantitative-model driven.

Future LLM support may be added as advisory/context assistance, with governance approval required before any order-authoritative LLM mode.

---

END OF README
