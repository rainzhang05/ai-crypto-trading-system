# AI CRYPTO TRADING SYSTEM
## PROJECT GOVERNANCE DOCUMENT
Version: 1.1
Status: AUTHORITATIVE

This document defines non-negotiable governance rules for architecture, finance, and operations.

Authoritative strategy behavior is defined in:

- `docs/specs/TRADING_LOGIC_EXECUTION_SPEC.md`
- `docs/specs/HISTORICAL_DATA_PROVIDER_AND_CONTINUOUS_TRAINING_SPEC.md`
- `docs/specs/OPERATOR_CONTROL_PLANE_AND_KRAKEN_ONBOARDING_SPEC.md`
- `docs/specs/LOCAL_FIRST_RUNTIME_AND_PRIVACY_SPEC.md`
- `docs/specs/MODEL_BUNDLE_DISTRIBUTION_AND_UPDATE_SPEC.md`
- `docs/specs/PRODUCTION_OPERATIONS_AND_RELIABILITY_SPEC.md`

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
5. Full available historical data must be backfilled for every governed training symbol.
6. Incremental ingestion of new market data must be continuous and deterministic.
7. Data gaps/late arrivals require explicit reconciliation evidence; silent repair is forbidden.

---

# 4. MODEL GOVERNANCE

Models must:

- use walk-forward validation
- avoid static split misuse
- log training windows and parameters
- support drift-aware retraining
- remain reproducible
- include per-coin specialist and global cross-asset modeling components
- enforce governed promotion gates before runtime activation

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

# 7A. OPERATOR INTERFACE AND EXCHANGE ONBOARDING GOVERNANCE

The system must provide a governed user-facing control plane for safe operation.

Required operator interface capabilities:

- Governed settings updates for risk/strategy profiles.
- Runtime status visibility (health, mode, active risk gates, kill switch).
- Decision/prediction visibility with reason-code evidence.
- Holdings and per-asset chart visibility.

Interface constraints:

- Frontend/operator tools must never bypass runtime risk gates or schema constraints.
- Parameter bounds are enforced server-side; UI validation is advisory only.
- Every settings change must be versioned, attributable, and replay-auditable.

Kraken onboarding governance requirements:

- Connection path must be user-guided and minimally complex.
- API key scope checks must enforce minimum required permissions.
- Withdrawal capability must be explicitly disallowed for trading keys.
- Secrets must be handled through secure storage pathways and never logged in plaintext.
- Live enablement requires explicit user confirmation after connectivity validation.

---

# 7B. LOCAL-FIRST RUNTIME AND PRIVACY GOVERNANCE

Core trading operation must be local-first:

- users must be able to run setup and runtime control fully on local machines
- mandatory cloud dependency is not allowed for core trading operation
- cloud services, when used, must remain optional extensions (backup/sync/update channels)

Local security/privacy requirements:

- Kraken credentials must be stored through approved secure OS credential stores (macOS Keychain for macOS build target)
- plaintext API secrets are prohibited in logs, config files, crash reports, and telemetry payloads
- local audit logs must preserve deterministic traceability while avoiding secret leakage

---

# 7C. MODEL BUNDLE GOVERNANCE

Model and inference artifacts are governed repository assets:

- inference-ready artifacts must be versioned in this repository and continuously updated via governed git workflow
- users must not start from an empty/untrained model state on first install
- bundle compatibility (app/backend/model) must be versioned and enforced
- update workflow must support verification, atomic install, and rollback on failure
- macOS app update/sync channel must retrieve artifacts from this GitHub repository path set

---

# 7D. HISTORICAL DATA AND CONTINUOUS TRAINING GOVERNANCE

Historical data + retraining governance requirements:

- A deep-history external provider adapter is mandatory for model-training backfill scope.
- Phase 6A source policy is restricted to `COINAPI` + `KRAKEN_PUBLIC` only.
- Training universe must be versioned and explicitly documented.
- Universe V1 is the top-30 non-stable governed set defined in:
  - `docs/specs/HISTORICAL_DATA_PROVIDER_AND_CONTINUOUS_TRAINING_SPEC.md`
- Retraining must run continuously (scheduled and/or drift-triggered) with deterministic lineage evidence.
- Provider credential handling must follow secure secret policies; secrets must never appear in logs/artifacts.
- Phase 6A credential surface must support:
  - `HIST_MARKET_DATA_PROVIDER`
  - `HIST_MARKET_DATA_API_KEY`
  - `HIST_MARKET_DATA_API_SECRET` (provider-dependent)
  - `HIST_MARKET_DATA_BASE_URL` (provider-dependent)
  - `KRAKEN_PUBLIC_BASE_URL`
  - `UNIVERSE_RANKING_SOURCE`
  - `FORCE_LOCAL_DATA_FOR_TRAINING`
  - `ALLOW_PROVIDER_CALLS_DURING_TRAINING`

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

# 12. PHASE COVERAGE CLOSURE POLICY

Every phase implementation is incomplete until coverage closure is achieved for all executable artifacts introduced or modified by that phase.

Coverage model (mandatory):

- Python implementation coverage must remain 100% line and 100% branch for `backend/`, `execution/`, and `scripts/`.
- Non-Python executable artifacts must be 100% classified and validated via execution, equivalence, or contract checks.

Executable artifacts include SQL, shell scripts, workflow definitions, and infrastructure configs.

Phase completion evidence must include both deterministic validation gates and phase coverage closure evidence.

---

# 13. PRIORITY ORDER

When conflicts arise:

1. Capital Preservation
2. Deterministic Behavior
3. Risk Enforcement
4. Backtest/Replay Integrity
5. Optimization

---

END OF PROJECT GOVERNANCE DOCUMENT
