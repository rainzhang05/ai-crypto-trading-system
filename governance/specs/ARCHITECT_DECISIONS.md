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

1. Maximum drawdown hard stop = 20%.
2. No margin, no leverage.
3. Volatility-adjusted position sizing.
4. Walk-forward training validation.
5. Meta-learner stacking structure.
6. Correlation cluster exposure caps.
7. Slippage modeling inclusion.
8. Exact Kraken fee modeling (0.4% per trade).
9. Deterministic execution logic.
10. Hourly prediction cycle.

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

governance/phases/phase_1_deterministic_contract/SCHEMA_MIGRATION_PHASE_1B.md

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

No risk rule thresholds are modified:
- 20% hard drawdown remains unchanged.
- 8% cluster cap remains unchanged.
- 2% base position size remains unchanged.
- Kraken 0.4% fee remains unchanged.

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

- `governance/phases/phase_1_deterministic_contract/PHASE_1C_REVISION_C_SCHEMA_REPAIR_BLUEPRINT.sql`
- `governance/phases/phase_1_deterministic_contract/PHASE_1C_REVISION_C_TRIGGER_REPAIR.sql`
- `governance/phases/phase_1_deterministic_contract/IMPLEMENTATION_LOG_PHASE_1C.md`
- `governance/phases/phase_1_deterministic_contract/PHASE_1C_ARTIFACT_STATUS.md`

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
   - `governance/validations/PHASE_2_REPLAY_HARNESS_VALIDATION.sql`

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

END OF ARCHITECTURAL DECISIONS LOG
