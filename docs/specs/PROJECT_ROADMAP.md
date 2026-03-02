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
- `docs/specs/OPERATOR_CONTROL_PLANE_AND_KRAKEN_ONBOARDING_SPEC.md`
- `docs/specs/LOCAL_FIRST_RUNTIME_AND_PRIVACY_SPEC.md`
- `docs/specs/MODEL_BUNDLE_DISTRIBUTION_AND_UPDATE_SPEC.md`
- `docs/specs/HISTORICAL_DATA_PROVIDER_AND_CONTINUOUS_TRAINING_SPEC.md`
- `docs/specs/PRODUCTION_OPERATIONS_AND_RELIABILITY_SPEC.md`

---

# 1. HIGH-LEVEL SYSTEM ARCHITECTURE

Final system layers:

1. Data Layer (PostgreSQL + TimescaleDB)
2. Historical Data Provider & Archive Layer
3. Feature Engineering Layer
4. Model Training Layer
5. Model Inference Layer
6. Strategy Engine
7. Risk Engine
8. Execution Engine
9. Ledger & Portfolio Engine
10. Replay Harness
11. Backtest Orchestrator
12. Paper Trading Adapter
13. Live Trading Adapter
14. Exchange Onboarding & Credential Gateway
15. Local Runtime Service (Loopback Control API + Secure Secret Boundary)
16. Operator Control Plane (macOS Desktop App + Control APIs)
17. Monitoring & Alerting Layer
18. Model Bundle Distribution & Update Layer
19. Governance & Audit Layer

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

## PHASE 5 — PORTFOLIO & LEDGER ENGINE ✅ COMPLETED

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

Status:
- ✅ Runtime-owned deterministic hourly economic state materialization integrated into `execute_hour` for:
  - `portfolio_hourly_state`
  - `risk_hourly_state`
  - `cluster_exposure_hourly_state`
- ✅ Deterministic `cash_ledger` rows are generated from `order_fill` with side-specific cash-delta semantics including fee/slippage cash cost.
- ✅ Existing-row conflict policy enforced: hash-match idempotent behavior, hash mismatch hard-abort.
- ✅ BACKTEST bootstrap cash fallback integrated via `backtest_run.initial_capital`; PAPER/LIVE strict bootstrap requirement preserved.
- ✅ Replay parity comparisons extended to all Phase 5 economic artifacts.
- ✅ CLI output surfaces include Phase 5 write counts for execution/replay observability.
- ✅ Phase 5 SQL validation gate added and wired into integration harness (`PHASE_5_PORTFOLIO_LEDGER_VALIDATION.sql`).

Phase 5 execution contract (authoritative handoff from Phase 4):

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

Phase 5 implemented surfaces:

- `execution/replay_engine.py` (planning + deterministic economic artifact emission)
- `execution/runtime_writer.py` (row builders/inserts/hash materialization for economic tables)
- `execution/deterministic_context.py` (load prior economic state surfaces for deterministic roll-forward)
- `scripts/replay_cli.py` (hour execution/replay result surfaces for Phase 5 artifacts)
- `tests/` + `docs/validations/` (new Phase 5 SQL gate and parity/invariant coverage)

---

## PHASE 6A — HISTORICAL DATA FOUNDATION & CONTINUOUS TRAINING BOOTSTRAP

Implement:

- Canonical historical data provider adapter (deep-history capable)
- Kraken public market-data adapter for venue-aligned reconciliation
- Full available-history backfill for all Universe V1 symbols
- Incremental sync for newly published market data
- Late-arrival reconciliation with deterministic correction evidence
- Dataset materialization with deterministic dataset hashes
- Per-coin + global + ensemble training orchestration bootstrap
- Scheduled and drift-triggered retraining automation hooks
- Hindcast/forecast evaluation gates for continuous quality measurement

Training universe policy:

- Universe V1 is fixed to top-30 non-stable symbols defined in:
  - `docs/specs/HISTORICAL_DATA_PROVIDER_AND_CONTINUOUS_TRAINING_SPEC.md`
- Universe V1 symbols:
  - `BTC, ETH, BNB, XRP, SOL, TRX, ADA, BCH, XMR, LINK, XLM, HBAR, LTC, AVAX, ZEC, SUI, SHIB, TON, DOT, UNI, AAVE, TAO, NEAR, ETC, ICP, POL, KAS, ALGO, FIL, APT`
- Universe changes require versioned governance updates (`UNIVERSE_V2+`).

Provider/key readiness requirements:

- Historical provider API credentials and endpoint configuration must be supported.
- Kraken private trading keys are not required for Phase 6A.

Acceptance:

- Full available history is backfilled for all Universe V1 symbols.
- Continuous sync is automated and deterministic.
- Data quality gates (gaps, duplicates, timestamp ordering) are enforced.
- Multi-model training bootstrap is operational on governed datasets.
- Autonomous retraining runs with governed promotion gates and periodic operator review workflow.

---

## PHASE 6B — BACKTEST ORCHESTRATOR

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

## PHASE 8A — KRAKEN ACCOUNT ONBOARDING & CREDENTIAL GATEWAY

Implement:
- Guided Kraken connection wizard flow
- Required-scope API key validation checks
- Enforced no-withdrawal key policy checks
- Secure secret storage integration (no plaintext persistence/logging)
- Connection smoke tests (balances, permissions, order endpoint reachability)
- Paper-first onboarding default with explicit live enable confirmation

The primary objective is the easiest safe path for users to connect their own Kraken account.

---

## PHASE 8B — LOCAL RUNTIME SERVICE AND CONTROL API

Implement:
- local runtime daemon lifecycle (install/start/stop/status)
- loopback-only control API authentication/session model
- deterministic runtime state transitions for local operator commands
- macOS Keychain integration for Kraken credential retrieval
- local audit log path standards and secret-redaction guarantees

Acceptance:
- runtime is fully controllable locally without mandatory cloud dependency
- no plaintext credential leakage in logs/config/crash output

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

## PHASE 9A — OPERATOR CONTROL PLANE (FRONTEND)

Implement:
- macOS SwiftUI desktop operator app
- Governed settings editor for risk/strategy profiles
- setup wizard with paper-first gate and explicit live-risk confirmation
- Runtime status dashboard (mode, health, risk gates, kill-switch state)
- Decision and prediction timeline views with reason-code evidence
- Holdings/lot inventory view and per-asset performance summary
- Asset chart views (price, exposure, and action overlays)
- Replay/audit links for every operator-visible decision

Constraints:
- No direct database mutation from frontend.
- All write actions route through governed APIs with versioned audit evidence.
- No UI path may bypass runtime risk constraints.

---

## PHASE 9B — macOS APP PACKAGING, INSTALLER, AND FIRST-RUN UX

Implement:
- signed macOS app packaging and installer flow
- first-run setup sequence (runtime readiness, credential check, paper-first gate)
- upgrade-safe local state migration for app/runtime versions
- desktop-level start/stop and health indicators for local runtime

Acceptance:
- users can install and run desktop control plane without manual developer tooling
- first-run flow deterministically enforces onboarding and safety prerequisites

---

## PHASE 9C — BUDGET AND LIMIT EXTENSIONS

Implement:
- global exposure cap policy surfaces (percent/absolute)
- per-quote-currency cap policy surfaces for `CAD`, `USD`, `USDC`
- runtime enforcement and reason-code logging for each cap dimension
- onboarding defaults and validation for mixed cap policy configurations

Acceptance:
- no order is emitted when any configured global/per-currency limit is violated
- violations are visible in operator timeline with deterministic reason codes

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

## PHASE 10A — MODEL BUNDLE RELEASE AND ONE-CLICK UPDATER

Implement:
- signed GitHub Release artifact bundles for inference-ready models/metadata
- model bundle manifest contract with compatibility ranges and checksum/signature fields
- in-app one-click update flow with verification and compatibility checks
- atomic swap install strategy with rollback-on-failure
- update audit trail surfaced in local logs/operator UI

Acceptance:
- users can update model bundles without rebuilding project
- tampered/incompatible bundles are rejected deterministically
- previous working bundle is restored on failed update

---

## PHASE 10B — VERSION COMPATIBILITY GOVERNANCE

Implement:
- explicit compatibility matrix for app/backend/model bundle versions
- compatibility policy in release process and runtime startup checks
- deterministic compatibility rejection messaging surfaced to operator UI

Acceptance:
- incompatible version combinations cannot become active
- compatibility matrix remains versioned, published, and test-validated

---

## PHASE 10C — LOCAL BACKUP, RESTORE, AND DISASTER RECOVERY

Implement:
- local backup strategy for runtime state, audit logs, and model bundles
- restore workflow and integrity checks
- documented RPO/RTO targets for local failure scenarios

Acceptance:
- backup and restore drills pass on supported local deployment targets
- restored state preserves deterministic replay continuity

---

## PHASE 10D — INCIDENT RESPONSE AND KILL-SWITCH OPERABILITY

Implement:
- operator-visible emergency stop/kill-switch control path
- incident severity classification and response runbook
- post-incident deterministic artifact capture workflow

Acceptance:
- kill-switch drills prove immediate admission halt with auditable evidence
- incident runbook is executable and repeatable by operators

---

## PHASE 10E — AUDIT EXPORT AND SUPPORT OPERATIONS

Implement:
- deterministic audit export package format for support/compliance
- support diagnostics bundle with secret redaction guarantees
- operator documentation for evidence sharing and replay reproduction

Acceptance:
- audit export package is reproducible and replay-verifiable
- support bundles contain no plaintext secret leakage

---

## PHASE 10F — DATA RETENTION, PRIVACY LIFECYCLE, AND ERASURE CONTROLS

Implement:
- retention policy for local logs, feature cache, and model artifact history
- user-visible local data export/delete controls
- privacy policy alignment checks in release process

Acceptance:
- retention and deletion controls are test-validated
- privacy lifecycle behavior is documented and auditable

---

## PHASE 10G — ARTIFACT TRUST POLICY AND KEY ROTATION

Implement:
- artifact signing trust policy and signer lifecycle governance
- key rotation runbook and emergency key revocation process
- runtime trust-store update and revoked-key rejection path

Acceptance:
- rotated/revoked keys behave per policy in update/install verification
- trust policy enforcement is verified in release validation pipeline

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
- External historical-data provider adapter setup + credential bootstrap
- Local full-history backfill and continuous incremental sync pipeline
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

Cloud staging is optional for local-first product operation and must not become a mandatory prerequisite for core trading control.

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
- Full available-history data ingestion and continuous incremental sync are operational for governed training universes
- Per-coin specialist and global model retraining pipelines run continuously with deterministic lineage and governed promotion gates
- Live trading runs without invariant violation
- Adaptive horizon decisions are replay-reconstructable from stored state
- Monitoring detects anomalies
- Users can safely connect Kraken accounts through a guided onboarding path with validated permissions and secure secret handling
- Local runtime service enables secure local-only control via authenticated loopback API
- Operator frontend (macOS) allows governed settings changes, runtime observability, predictions/decisions inspection, and holdings/chart visibility without risk bypass
- Global and per-currency (`CAD`, `USD`, `USDC`) budget caps are enforced with deterministic reason-code evidence
- Model bundle lifecycle supports signed distribution, compatibility gating, and rollback-safe one-click updates
- Audit reconstruction reproducible from hash chain
- Capital preservation rules cannot be bypassed
- Every phase implementation is incomplete until coverage closure is achieved for all executable artifacts introduced or modified by that phase.
- Python implementation coverage remains 100% line and 100% branch for `backend/`, `execution/`, and `scripts/`.
- Non-Python executable artifacts are 100% classified and validated (execution, equivalence, or contract check).

---

# 6A. PHASE COVERAGE CLOSURE POLICY

Coverage closure is mandatory for phase sign-off:

1. A phase cannot be marked complete if any executable artifact added/changed by that phase lacks coverage closure evidence.
2. Executable artifact scope includes SQL, shell scripts, workflow definitions, and infrastructure configuration files.
3. Historical artifacts may be excluded only by explicit policy with documented rationale and compensating checks.
4. Coverage closure evidence must be reproducible in the clean-room deterministic pipeline.

---

# 6B. PRODUCTION COMPLETENESS TRACKING

Mandatory production-completeness areas are explicitly covered by roadmap phases:

1. Compatibility governance (`PHASE 10B`).
2. Backup/restore and disaster recovery (`PHASE 10C`).
3. Incident response and kill-switch operability (`PHASE 10D`).
4. Audit export and support operations (`PHASE 10E`).
5. Data retention/privacy lifecycle controls (`PHASE 10F`).
6. Artifact trust policy and key rotation (`PHASE 10G`).

---

# 7. CURRENT POSITION

Active Phase:
Phase 6A — Historical Data Foundation & Continuous Training Bootstrap (Ready to Start)

Blockers:
- None on deterministic core, replay harness closure, Phase 3 runtime completion, Phase 4 lifecycle closure, or Phase 5 portfolio/ledger closure.
- Phase 5 closure complete; Phase 6A execution can begin.

Deterministic core, replay harness, governed Phase 3 runtime, deterministic Phase 4 order lifecycle, and deterministic Phase 5 portfolio/ledger runtime (Phase 1A/1B/1C/1D/2/3/4/5) are structurally complete and validated for Phase 6A entry.

---

END OF MASTER PROJECT ROADMAP
