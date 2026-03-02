# AI CRYPTO TRADING SYSTEM — MASTER PROJECT ROADMAP
Version: 1.1  
Status: Authoritative Execution Roadmap  
Scope: From Deterministic Core Hardening → Production Deployment  

---

# 0. PROJECT OBJECTIVE

Build a production-grade, deterministic, auditable AI crypto trading system with:

- Full deterministic replay
- Hash-perfect lineage
- Strict capital preservation
- Append-only financial ledger
- Walk-forward validated models
- Adaptive model-driven holding horizon (short-term to long-term)
- Continuous live decisioning (event-driven evaluation)
- User-configurable risk/exposure profiles (with governed defaults)
- Risk-enforced execution
- Backtest ↔ Paper ↔ Live parity
- Regulatory-grade reconstruction capability

Capital Preservation > Determinism > Risk Enforcement > Backtest Integrity > Optimization.

Authoritative strategy execution rules are defined in:

- `docs/specs/TRADING_LOGIC_EXECUTION_SPEC.md`

---

# 1. HIGH-LEVEL SYSTEM ARCHITECTURE

Final system layers:

1. Data Layer (PostgreSQL + TimescaleDB)
2. Feature Engineering Layer
3. Model Training Layer
4. Model Inference Layer
5. Strategy Engine
6. Risk Engine
7. Execution Engine
8. Ledger & Portfolio Engine
9. Replay Harness
10. Backtest Orchestrator
11. Paper Trading Adapter
12. Live Trading Adapter
13. Monitoring & Alerting Layer
14. Governance & Audit Layer

---

# 2. PHASE ROADMAP (AUTHORITATIVE SEQUENCE)

---

## PHASE 0 — DATA LAYER FOUNDATION ✅ COMPLETED

- Core schema
- Hypertables
- Append-only enforcement
- Risk constraints encoded
- No-leverage enforcement
- Fee guardrails
- Deterministic join keys

Artifact:
- MASTER_SCHEMA_DDL_CONTRACT

---

## PHASE 1 — DETERMINISTIC CONTRACT

### Phase 1A — Integrity Hardening Design ✅ COMPLETED

- Auditor remediation
- Critical risk elimination plan
- Dual-hour execution model
- Ledger arithmetic chain
- Hash propagation DAG
- Walk-forward structural enforcement
- Cluster exposure structural enforcement

---

### Phase 1B — Schema Migration Blueprint (Architect) ✅ COMPLETED

Deliverable:
- docs/phases/phase_1_deterministic_contract/SCHEMA_MIGRATION_PHASE_1B.md

Output:
- Ordered migration phases
- DDL operations
- Backfill plan
- Regeneration matrix
- Deterministic constraints

---

### Phase 1C — Schema Migration Implementation (Implementation Agent) ✅ COMPLETED

Tasks:
- Execute DDL migration
- Apply dual-hour refactor
- Implement ledger chain
- Introduce new hash columns
- Introduce cluster tables
- Enforce FK expansion
- Apply deferrable constraints

Then:
- Regenerate invalidated artifacts
- Recompute ledger
- Recompute risk states

Status:
- ✅ Revision B migration/cutover completed
- ✅ Revision C schema repair completed
- ✅ Revision C minimal drift-correction loop completed
- ✅ Pre-1D readiness audit: all checks passing

---

### Phase 1D — Deterministic Replay Validation ✅ COMPLETED

Build:
- Replay CLI
- Hash recomputation engine
- Ledger chain verifier
- Invariant test suite

Validation Requirements:
- Exact hash parity
- Cash_t = Cash_{t-1} + Δ
- No cross-account contamination
- No quantity overflow
- No lookahead
- Walk-forward separation proof

Status:
- ✅ Deterministic execution runtime modules implemented and integrated.
- ✅ Replay parity harness implemented and validated.
- ✅ Runtime validation gates executed with zero violations.
- ✅ Deterministic replay parity checks passed.

Phase 2 entry was unblocked after Phase 1D closure.

---

## PHASE 2 — REPLAY HARNESS ARCHITECTURE ✅ COMPLETED

Build:
- Snapshot boundary loader
- Canonical serialization engine
- Deterministic hash DAG recomputation
- Failure classification engine
- Replay comparison engine

Deliverable:
- Deterministic replay tool

System must produce:
REPLAY PARITY: TRUE

Status:
- ✅ Snapshot boundary loader implemented.
- ✅ Canonical serialization engine implemented.
- ✅ Deterministic hash DAG recomputation implemented.
- ✅ Failure classification engine implemented.
- ✅ Replay comparison engine implemented.
- ✅ Deterministic replay tool implemented (`replay-tool`) with parity status output.
- ✅ Governance validation gate added (`PHASE_2_REPLAY_HARNESS_VALIDATION.sql`).
- ✅ Clean-room replay-tool smoke check added to test pipeline.

---

## PHASE 3 — RISK ENGINE RUNTIME IMPLEMENTATION ✅ COMPLETED

Implement:
- Drawdown tier logic
- Kill switch enforcement
- Volatility-adjusted sizing runtime
- Exposure cap enforcement with selectable unit mode (percent / absolute amount)
- Cluster cap enforcement with selectable unit mode (percent / absolute amount)
- Risk-state state machine
- Adaptive horizon risk gating (allow extended holds only while risk/edge conditions remain valid)
- Severe-loss recovery evaluation mode (prediction-led hold/de-risk/exit)

Runtime must exactly match schema invariants.

Phase 3 strategy/risk runtime delivery must implement:

- `docs/specs/TRADING_LOGIC_EXECUTION_SPEC.md`

Status:
- ✅ Governed `risk_profile` + `account_risk_profile_assignment` persistence implemented.
- ✅ Deterministic context loading extended with profile, volatility features, and positions.
- ✅ Volatility-adjusted sizing runtime implemented with deterministic fallback behavior.
- ✅ Adaptive horizon + severe-loss recovery intent routing integrated into planner/runtime flow.
- ✅ Decision-trace risk-event evidence wiring implemented per signal.
- ✅ Phase 3 governance SQL validation gate implemented and wired into clean-room pipeline.

---

## PHASE 4 — ORDER LIFECYCLE ENGINE ✅ COMPLETED

Implement:
- Signal → Order → Fill → Lot → Trade
- Continuous campaign lifecycle logic
- Retry logic
- Partial fill handling
- Exchange adapter abstraction

Must preserve:
- Long-only enforcement
- No-leverage enforcement
- Causal ordering
- No fixed maximum holding-time cap

Status:
- ✅ Deterministic exchange adapter contract introduced.
- ✅ Deterministic simulator adapter implemented (order-book first, OHLCV fallback).
- ✅ Signal → Order → Fill → Lot → Trade lifecycle materialized with append-only writes.
- ✅ Partial fill + deterministic retry schedule implemented (`+1m`, `+2m`, `+4m`).
- ✅ FIFO lot allocation implemented for SELL fills with no-shorting guardrails.
- ✅ Replay parity extended to `order_fill`, `position_lot`, and `executed_trade`.
- ✅ Phase 4 validation gate added (`PHASE_4_ORDER_LIFECYCLE_VALIDATION.sql`) and wired into pipeline.

---

## PHASE 5 — PORTFOLIO & LEDGER ENGINE (READY TO START)

Implement:
- Deterministic ledger writer
- Ledger hash chain
- Portfolio reconciler
- Exposure aggregator
- Cluster state generator
- Risk-state writer

Must guarantee:
- Arithmetic continuity
- No drift
- Immutable economic record

Phase 5 entry contract (authoritative handoff from Phase 4):

- Input artifacts are authoritative from completed Phase 4 tables:
  - `order_fill`
  - `position_lot`
  - `executed_trade`
  - `order_request` / `trade_signal` / `risk_event` evidence traces
- Economic writers must remain deterministic and append-only compatible:
  - `cash_ledger`
  - `portfolio_hourly_state`
  - `cluster_exposure_hourly_state`
  - `risk_hourly_state`
- Writer outputs must preserve:
  - no leverage
  - arithmetic continuity
  - replay reproducibility
  - schema contract equivalence with `schema_bootstrap.sql`

Phase 5 starting implementation surfaces:

- `execution/replay_engine.py` (planning + deterministic economic artifact emission)
- `execution/runtime_writer.py` (row builders/inserts/hash materialization for economic tables)
- `execution/deterministic_context.py` (load prior economic state surfaces for deterministic roll-forward)
- `scripts/replay_cli.py` (hour execution/replay result surfaces for Phase 5 artifacts)
- `tests/` + `docs/validations/` (new Phase 5 SQL gate and parity/invariant coverage)

---

## PHASE 6 — BACKTEST ORCHESTRATOR

Implement:
- Walk-forward training loop
- Fold generation
- Model training
- Hyperparameter logging
- MLflow artifact storage
- Fold metric storage
- Validation gating
- Deterministic inference simulation

Include:
- Kraken fee modeling
- Slippage modeling
- Execution delay modeling
- Risk enforcement during simulation

No static train/test split allowed.

---

## PHASE 7 — PAPER TRADING ADAPTER

Implement:
- Live market data ingestion
- Real-time feature generation
- Real-time model inference
- Risk runtime
- Order simulation
- Ledger writing
- Replay compatibility

Paper trading must run minimum 30 days before live.

---

## PHASE 8 — LIVE EXECUTION ADAPTER

Implement:
- Kraken API integration
- Secure credential handling
- Order placement
- Fill reconciliation
- Retry with exponential backoff
- Real-time ledger updates
- Real-time risk enforcement
- Event-driven continuous decision triggers

No risk bypass allowed.

---

## PHASE 9 — MONITORING & OBSERVABILITY

Implement:
- Drawdown alerts
- Kill switch alerts
- Hash mismatch alerts
- Execution failure alerts
- Slippage anomaly detection
- API health monitoring
- Capital exposure dashboards

---

## PHASE 10 — PRODUCTION HARDENING

Perform:
- Concurrency testing
- Race condition testing
- Ledger stress testing
- Replay under load
- Failover simulation
- Backup restore test
- Disaster recovery drill
- Capital scaling review
- Regulatory audit reconstruction test

Only after this phase:
Live capital scaling permitted.

---

## PHASE 11 — OPTIONAL LLM ASSIST LAYER (NON-AUTHORITATIVE)

Implement (optional, governance-gated):

- LLM advisory/context layer for anomaly explanation and strategy assistance
- Strict non-authoritative integration in initial release
- Full audit logging of LLM inputs/outputs when enabled

Order-authoritative LLM behavior requires separate explicit governance approval.

---

# 3. DEVELOPMENT ENVIRONMENT STRATEGY

## Stage 1 — Local Development (Mandatory)

- Dockerized PostgreSQL + Timescale
- Local MLflow
- Local deterministic testing
- Local backtest
- Local replay validation

## Stage 2 — Cloud Staging

- Cloud SQL
- Cloud Run
- Secret Manager
- Artifact Registry
- Scheduler

## Stage 3 — Production

- Monitoring enabled
- Alerting enabled
- Minimal capital allocation
- Gradual scaling

---

# 4. AGENT RESPONSIBILITY MATRIX

Architect:
- Structural integrity
- Constraint enforcement
- Deterministic contract alignment

Auditor:
- Adversarial verification
- Leakage detection
- Risk enforcement validation
- Financial impact analysis

Implementation:
- Code execution
- No logic modification
- Deterministic adherence
- Modular design

Project Manager:
- Phase sequencing
- Artifact freezing
- Progress gating
- Risk escalation
- State transfer management

---

# 5. ARTIFACT STRUCTURE

All phase artifacts must reside under:

/docs/phases/<phase_name>/

Example:

/docs/phases/phase_1_deterministic_contract/
    SCHEMA_MIGRATION_PHASE_1B.md
    PHASE_1C_REVISION_B_SCHEMA_MIGRATION.md
    PHASE_1C_REVISION_C_SCHEMA_REPAIR_BLUEPRINT.sql
    PHASE_1C_REVISION_C_TRIGGER_REPAIR.sql
    IMPLEMENTATION_LOG_PHASE_1C.md

Artifacts must:
- Be versioned
- Be immutable once frozen
- Be referenced by subsequent phases

---

# 6. PROJECT COMPLETION DEFINITION

Project is considered complete when:

- Deterministic replay passes for all runs
- Ledger chain proves arithmetic continuity
- Risk caps structurally enforced
- Cluster caps structurally enforced
- Walk-forward contamination impossible
- Model activation gated by OOS validation
- Live trading runs without invariant violation
- Adaptive horizon decisions are replay-reconstructable from stored state
- Monitoring detects anomalies
- Audit reconstruction reproducible from hash chain
- Capital preservation rules cannot be bypassed

---

# 7. CURRENT POSITION

Active Phase:
Phase 5 — Portfolio & Ledger Engine (Ready to Start)

Blockers:
- None on deterministic core, replay harness closure, Phase 3 runtime completion, or Phase 4 lifecycle closure.
- Phase 4 closure complete; Phase 5 execution can begin.

Deterministic core, replay harness, governed Phase 3 runtime, and deterministic Phase 4 order lifecycle (Phase 1A/1B/1C/1D/2/3/4) are structurally complete and validated for Phase 5 entry.

---

END OF MASTER PROJECT ROADMAP
