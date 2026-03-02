# AI CRYPTO TRADING SYSTEM
## ARCHITECTURAL DECISIONS LOG

This document records all structural and architectural decisions made during development.

No major architectural modification is valid unless recorded here.

Each entry must include:

- Decision ID
- Date
- Module Affected
- Description
- Reason
- Risk Impact
- Backtest Impact
- Approval Status

---

# DECISION FORMAT TEMPLATE

---

## DECISION ID: ARCH-XXXX

Date:
Module Affected:

### Description
(What structural change is being made?)

### Reason
(Why is this change necessary?)

### Risk Impact
(Does this affect capital exposure, slippage, sizing, drawdown rules, etc?)

### Backtest Impact
(Will historical results change? Is retraining required?)

### Approval
Architect:
Auditor:
Status: Approved / Rejected / Pending

---

# INITIAL ARCHITECTURAL LOCKS

The following items are locked per Master Specification and cannot be changed without explicit documented approval:

1. Drawdown/entry-circuit-breaker framework (profile defaults governed; values configurable by policy).
2. No margin, no leverage.
3. Volatility-adjusted position sizing.
4. Walk-forward training validation.
5. Meta-learner stacking structure.
6. Exposure cap framework (supports percent and absolute modes).
7. Slippage modeling inclusion.
8. Exact Kraken fee modeling (0.4% per trade).
9. Deterministic execution logic.
10. Recurring deterministic re-evaluation cycle (continuous live target with replay-safe context).

Interpretation note:
- Historical decision entries document constraints and defaults that were active at the time of each decision.
- Current strategy authority for live behavior is `TRADING_LOGIC_EXECUTION_SPEC.md` and newer decisions (especially ARCH-0005 and ARCH-0006).

---

# VERSION HISTORY

Version 1.0
- Initial quantitative core architecture defined.
- All predictive models active from initial deployment.
- LLM removed from trading logic.
- Production-grade governance enforced.

Version 1.1
- Cloud infrastructure migrated from Microsoft Azure to Google Cloud Platform (GCP).
- Trading logic, risk rules, and modeling architecture remain unchanged.

Version 1.2
- Strategy policy upgraded to continuous live decisioning with profile-configurable risk/exposure controls.
- LLM support path changed from excluded to optional future advisory mode (non-authoritative unless explicitly approved).

---

# ARCHITECTURAL DECISIONS

---

## DECISION ID: ARCH-0001

Date: 2026-02-27  
Module Affected: Infrastructure & DevOps Layer

### Description
Cloud provider migrated from Microsoft Azure to Google Cloud Platform (GCP).

Infrastructure components updated as follows:

- Azure App Service → Cloud Run  
- Azure Container Registry → Artifact Registry  
- Azure Blob Storage → Cloud Storage (GCS)  
- Azure PostgreSQL → Cloud SQL (PostgreSQL)  
- Azure Secret Management → GCP Secret Manager  
- Azure Monitoring & Logging → Cloud Logging & Monitoring  
- Azure Scheduler → Cloud Scheduler  

No changes were made to trading logic, modeling architecture, risk management, or backtesting rules.

### Reason
Strategic infrastructure decision to standardize deployment and operations on Google Cloud Platform.

### Risk Impact
No impact on:

- Position sizing
- Fee modeling
- Slippage modeling
- Drawdown enforcement
- Correlation caps
- Meta-learner structure
- Deterministic execution

Infrastructure layer change does not alter capital allocation logic.

### Backtest Impact
None.

Historical backtests remain valid as financial logic is unchanged.

### Approval
Architect: Approved  
Auditor: Approved  
Status: Approved

---

# RULES

1. If it affects capital allocation, it must be logged.
2. If it affects model structure, it must be logged.
3. If it affects feature construction, it must be logged.
4. If it affects risk logic, it must be logged.
5. If it affects backtest results, it must be logged.

Failure to log structural changes invalidates backtest credibility.

---

## DECISION ID: ARCH-0002

Date: 2026-02-28  
Module Affected: Core Data Layer, Replay Contract, Risk Enforcement Layer, Execution Lineage, Model Lineage

### Description

Approval of Phase 1B — Deterministic Contract Migration.

This decision formalizes the structural migration defined in:

docs/phases/phase_1_deterministic_contract/SCHEMA_MIGRATION_PHASE_1B.md

The migration introduces:

1. Account-complete run context binding:
   - All replay-authoritative tables bind to
     (run_id, account_id, run_mode, origin_hour_ts_utc).

2. Dual-hour execution model:
   - origin_hour_ts_utc = decision anchor.
   - hour_ts_utc / event_ts_utc = actual economic event time.
   - Structural decoupling of decision and execution hours.

3. Ledger chain hardening:
   - ledger_seq (deterministic ordering).
   - balance_before continuity enforcement.
   - prev_ledger_hash and ledger_hash cryptographic linkage.
   - economic_event_hash uniqueness.
   - Full deterministic ledger regeneration required.

4. Hash propagation DAG:
   - row_hash on all replay-authoritative tables.
   - upstream_hash / parent_hash lineage propagation.
   - run_seed_hash integration into all preimages.
   - replay_root_hash materialization in replay_manifest.

5. Walk-forward structural enforcement:
   - model_training_window bound to backtest_fold_result.
   - training_window_id + fold lineage required for BACKTEST.
   - Contamination guard (train_end < prediction_hour < valid_end).
   - Activation gate required for PAPER/LIVE predictions.

6. Risk-state binding enforcement:
   - trade_signal and order_request bound to exact risk_state_run_id.
   - Risk halt/kill switch enforced via deferred trigger.
   - Orders structurally blocked when risk state forbids entries.

7. Correlation cluster structural enforcement:
   - correlation_cluster registry.
   - asset_cluster_membership (time-bounded).
   - cluster_exposure_hourly_state keyed to risk state.
   - Admission-time cap enforcement (≤ 8% of PV).

8. Economic formula enforcement:
   - fee_paid = fill_notional × fee_rate.
   - slippage_cost enforced via formula.
   - executed_trade net_pnl hard constraint.

9. Append-only enforcement:
   - UPDATE/DELETE blocked on replay-authoritative tables.
   - Legacy tables archived at cutover.

This migration requires:

- Full freeze at cutpoint T0.
- Full deterministic regeneration of decision, execution, risk, and accounting tables.
- No in-place mutation of append-only history.
- Replay parity validation before unlocking production writes.

---

### Reason

The prior schema allowed:

- Cross-account context ambiguity.
- Hour-coupled execution constraints preventing multi-hour lifecycle accuracy.
- Non-sequenced ledger entries.
- Partial hash lineage.
- Externalized walk-forward validation enforcement.
- Policy-level (not structural) cluster cap enforcement.

These conditions violate:

- Deterministic replay guarantees.
- Capital attribution isolation.
- Audit-grade financial reconstruction.
- Strict governance requirements defined in PROJECT_GOVERNANCE.md.
- Walk-forward and contamination controls defined in MASTER_SPEC.md.

Phase 1B eliminates these structural weaknesses and upgrades the system to a cryptographically verifiable deterministic contract.

---

### Risk Impact

HIGH POSITIVE IMPACT.

This migration:

- Eliminates cross-account capital contamination.
- Eliminates silent ledger drift.
- Prevents cluster cap bypass.
- Prevents risk halt bypass.
- Blocks walk-forward leakage at insert time.
- Enforces fee/slippage correctness at schema level.
- Enables cryptographic replay attestation.

No risk rule thresholds are modified in the ARCH-0002 decision scope (historical baseline at that time):
- 20% drawdown-based entry halt policy remained unchanged.
- 8% cluster cap remained unchanged.
- 2% base position size remained unchanged.
- Kraken 0.4% fee remained unchanged.

This is structural hardening, not financial logic alteration.

---

### Backtest Impact

YES — FULL REGENERATION REQUIRED.

The following tables must be regenerated:

- run_context
- model_training_window
- backtest_fold_result
- feature_snapshot
- regime_output
- model_prediction
- trade_signal
- order_request
- order_fill
- position_lot
- executed_trade
- cash_ledger
- position_hourly_state
- portfolio_hourly_state
- risk_hourly_state
- risk_event
- cluster_exposure_hourly_state

Historical metrics may change due to:

- Strict fee/slippage formula enforcement.
- Deterministic ledger re-sequencing.
- Exact walk-forward window enforcement.

Backtests prior to Phase 1B are no longer governance-valid.

---

### Approval

Architect: Approved  
Auditor: Pending (post-implementation verification required)  
Status: Approved for Phase 1C Implementation

---

END OF DECISION ARCH-0002

---

## DECISION ARCH-0003 — PHASE 1C REVISION C CLOSURE

### Decision

Phase 1C deterministic-contract implementation is declared complete after Revision C repair closure.

Closure conditions satisfied:

- `_v2` trigger/function drift removed from active runtime paths.
- Walk-forward lineage and activation-gate bindings present and validated.
- Replay-critical hash surface hardened to non-nullable columns.
- No FK targets on hypertables.
- No residual `_v2` relations.
- Core deterministic integrity checks passing (cross-account isolation, ledger continuity, cluster cap, walk-forward contamination exclusion).
- Migration lock returned to `locked = FALSE` only after zero-violation gate.

### Artifacts

- `docs/phases/phase_1_deterministic_contract/PHASE_1C_REVISION_C_SCHEMA_REPAIR_BLUEPRINT.sql`
- `docs/phases/phase_1_deterministic_contract/PHASE_1C_REVISION_C_TRIGGER_REPAIR.sql`
- `docs/phases/phase_1_deterministic_contract/IMPLEMENTATION_LOG_PHASE_1C.md`
- `docs/phases/phase_1_deterministic_contract/PHASE_1C_ARTIFACT_STATUS.md`

### Status

Architect: Approved  
Auditor: Validation gate passed  
Status: Phase 1C closed; Phase 1D authorized to start

---

## DECISION ARCH-0004 — PHASE 2 REPLAY HARNESS ARCHITECTURE CLOSURE

Date: 2026-03-01  
Module Affected: Replay Harness Layer, Governance Validation Layer, Replay CLI

### Description

Phase 2 replay harness architecture is approved as implemented with deterministic tooling and governance gates.

Delivered components:

1. Snapshot boundary loader:
   - `execution/replay_harness.py::load_snapshot_boundary(...)`

2. Canonical serialization engine:
   - `execution/replay_harness.py::canonical_serialize(...)`

3. Deterministic hash DAG recomputation:
   - `execution/replay_harness.py::recompute_hash_dag(...)`

4. Failure classification engine:
   - `execution/replay_harness.py::classify_replay_failure(...)`

5. Replay comparison engine:
   - `execution/replay_harness.py::compare_replay_with_manifest(...)`

6. Deterministic replay tool surface:
   - `scripts/replay_cli.py` commands:
     - `replay-manifest`
     - `replay-window`
     - `replay-tool`
   - explicit status contract: `REPLAY PARITY: TRUE/FALSE`

7. Governance validation gate:
   - `docs/validations/PHASE_2_REPLAY_HARNESS_VALIDATION.sql`

8. Clean-room pipeline wiring:
   - `scripts/test_all.sh` executes Phase 2 validation SQL and replay-tool smoke check.

### Reason

Phase 2 is required to transform replay from module-level checks into a deterministic replay tool with auditable parity output and governance-enforced integrity gates. This closes the roadmap requirement:

- Deliverable: deterministic replay tool.
- System output: `REPLAY PARITY: TRUE`.

### Risk Impact

LOW / POSITIVE.

- No changes to position sizing, fee/slippage assumptions, exposure caps, drawdown thresholds, or order lifecycle semantics.
- No bypasses added around schema constraints, append-only controls, or runtime risk gating.
- Changes are additive to replay/audit validation and improve detection of replay-root and manifest drift.

### Backtest Impact

None to strategy economics.

- No model, signal, order, or ledger formula changes.
- Existing historical results remain governed by existing deterministic schema/runtime constraints.
- Replay attestation surface is stronger and more explicit.

### Approval

Architect: Approved  
Auditor: Validation gate passed  
Status: Approved; Phase 2 closed, Phase 3 authorized

---

## DECISION ARCH-0005 — ADAPTIVE HOLDING HORIZON POLICY

Date: 2026-03-01  
Module Affected: Strategy Layer, Model Output Contract, Governance Layer

### Description

The project policy is updated from fixed short-window holding assumptions to an adaptive, model-driven holding horizon.

Approved behavior:

- No global hard cap that forces all positions to close within a fixed window (for example, 24 hours).
- Positions may be held for short-term, medium-term, or long-term durations when model edge and risk state remain valid.
- Exit timing must be re-evaluated on every decision trigger using the latest data.
- "Best selling time" is treated as a continuously updated forecast target, not a static value assigned at entry.
- Tactical partial exits and tactical re-entries are allowed within a campaign to harvest short-term opportunities.
- Default policy may include a 20% new-entry circuit breaker; it is not a mandatory immediate full liquidation trigger for all open positions.

### Reason

Fixed short windows constrain strategy expressiveness and can force premature exits. The ensemble architecture is intended to adapt holding duration to evolving market conditions while preserving deterministic replay and risk-first controls.

### Risk Impact

MEDIUM / POSITIVE when combined with existing controls.

- Positive: avoids deterministic premature exits that can reduce risk-adjusted returns.
- Guardrails unchanged: drawdown halts, exposure caps, no-leverage, fee/slippage checks, and kill switch remain mandatory.
- Requirement: every horizon update and exit rationale must remain fully logged for replay reconstruction.
- Phase 0-2 compatibility is preserved: no mandatory schema change is required for this policy interpretation.

### Backtest Impact

Yes, strategy behavior may change and requires adaptive-horizon simulation in backtest/paper/live parity flows.

- Historical fixed-window assumptions are no longer governance-preferred.
- Backtest logic must evaluate rolling re-forecast exits under identical risk constraints.

### Approval

Architect: Approved  
Auditor: Runtime parity verification completed (Phase 3 validation gate passed)  
Status: Approved and implemented

---

## DECISION ARCH-0006 — CONTINUOUS LIVE POLICY AND CONFIGURABLE RISK PROFILES

Date: 2026-03-01  
Module Affected: Strategy Runtime, Risk Profile Layer, Product Configuration Interface

### Description

Policy is extended to require:

- Continuous live decisioning (event-driven), not fixed interval-only strategy behavior.
- User-configurable position/exposure controls through profile settings.
- Exposure controls supporting percent-of-portfolio and absolute-amount modes.
- Prediction-led exits and severe-loss recovery logic over fixed loss-threshold liquidation.

### Reason

Static thresholds and fixed decision intervals reduce adaptability to real-time market state transitions. Configurable profiles and continuous evaluation allow the system to optimize behavior under diverse user risk preferences while preserving deterministic governance.

### Risk Impact

MEDIUM / MANAGEABLE with governance controls.

- Positive: strategy flexibility and better timing responsiveness.
- Risk: misconfiguration risk is introduced.
- Mitigation: profile versioning, audit logging, safety bounds, and deterministic replay of profile state.

### Backtest Impact

Yes, backtest/paper/live logic must include:

- profile-parameter surfaces,
- unit-mode exposure enforcement,
- continuous/event-driven evaluation semantics.

Historical Phase 0-2 artifacts remain valid as deterministic scaffolding and historical baseline.

### Approval

Architect: Approved  
Auditor: Implementation-phase validation completed (Phase 3 closure)  
Status: Approved and implemented; Phase 4 authorized

---

## DECISION ARCH-0007 — PHASE 4 DETERMINISTIC ORDER LIFECYCLE CLOSURE

Date: 2026-03-02  
Module Affected: Execution Runtime, Replay Engine, Deterministic Context, Runtime Validation Layer

### Description

Phase 4 order lifecycle is formally closed with deterministic runtime implementation of:

- order intent derivation from signal outcomes,
- append-only order attempt rows (`order_request`) with deterministic retry schedule,
- deterministic fills (`order_fill`) via adapter abstraction,
- lot opening on BUY fills (`position_lot`),
- FIFO trade realization on SELL fills (`executed_trade`),
- replay parity extension for fill/lot/trade hashes.

The implementation uses a deterministic simulator adapter for Phase 4 and does not introduce live exchange connectivity in this phase.

### Reason

Execution determinism and capital-preserving lifecycle traceability are required before Phase 5 economic writer integration and before external venue connectivity phases.

### Risk Impact

MEDIUM / CONTROLLED.

- Positive: lifecycle causality and replay visibility are now complete at order/fill/lot/trade level.
- Controlled risk: SELL allocation now enforces no-shorting behavior with explicit reason-code evidence for insufficient lot coverage.
- No leverage policy and append-only protections remain schema-enforced.

### Backtest Impact

Yes, runtime artifact graph now includes additional deterministic execution tables:

- `order_fill`
- `position_lot`
- `executed_trade`

Historical deterministic scaffolding remains valid; replay contract is extended, not loosened.

### Approval

Architect: Approved  
Auditor: Validation completed (`pytest -q`, `scripts/test_all.sh`, Phase 4 SQL gate)  
Status: Approved and implemented; Phase 5 authorized (closure recorded in ARCH-0008)

---

## DECISION ARCH-0008 — PHASE 5 DETERMINISTIC PORTFOLIO/LEDGER CLOSURE

Date: 2026-03-02  
Module Affected: Execution Runtime, Deterministic Context, Replay Engine, Runtime Writer, Runtime Validation Layer

### Description

Phase 5 is formally closed with deterministic runtime ownership of economic state materialization and cash-ledger writes:

- runtime-owned hourly writers for:
  - `portfolio_hourly_state`
  - `risk_hourly_state`
  - `cluster_exposure_hourly_state`
- deterministic `cash_ledger` emission from `order_fill` artifacts with hash-linked continuity
- deterministic bootstrap-capital policy for ledger initialization and strict abort behavior for invalid bootstrap contexts
- replay parity extension for all Phase 5 economic artifacts
- CLI/runtime validation surfaces extended for Phase 5 write counts and SQL gate coverage

### Reason

Phase 4 lifecycle determinism requires deterministic economic ownership to close accounting continuity and replay-complete attestation before orchestration/live adapter phases.

### Risk Impact

MEDIUM / CONTROLLED.

- Positive: deterministic ownership of cash/portfolio/risk/cluster state removes implicit preseed assumptions and reduces risk of silent economic drift.
- Controlled risk: existing-row conflict handling is strict (hash-match idempotent, hash-mismatch abort).
- No-leverage, append-only, and risk-tier governance controls remain preserved.

### Backtest Impact

Yes, runtime artifact graph now includes deterministic Phase 5 economic tables as replay-authoritative surfaces:

- `cash_ledger`
- `portfolio_hourly_state`
- `cluster_exposure_hourly_state`
- `risk_hourly_state`

Historical deterministic artifacts remain valid; replay contract is extended, not loosened.

### Approval

Architect: Approved  
Auditor: Validation scope extended through Phase 5 replay parity and SQL gates  
Status: Approved and implemented; Phase 6 authorized

---

END OF ARCHITECTURAL DECISIONS LOG
