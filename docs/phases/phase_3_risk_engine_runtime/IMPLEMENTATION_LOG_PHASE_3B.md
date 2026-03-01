# IMPLEMENTATION_LOG_PHASE_3B

## Scope
Phase 3 completion slice: governed risk-profile persistence, volatility-adjusted sizing,
adaptive horizon gating, severe-loss recovery intent routing, and phase validation wiring.

## Implemented

1. Governed profile persistence schema
- Added `risk_profile` canonical table with:
  - exposure mode/value surfaces (percent / absolute)
  - severe-loss trigger
  - volatility sizing parameters
  - adaptive/recovery thresholds
  - deterministic `row_hash`
- Added `account_risk_profile_assignment` with effective window and deterministic `row_hash`.
- Added append-only triggers for both new tables.

2. Deterministic context enrichment
- Extended `ExecutionContext` with:
  - `risk_profile`
  - `volatility_features`
  - `positions`
- Added deterministic loaders for:
  - active risk profile assignment
  - volatility feature snapshots
  - position hourly state
- Added validation guards for:
  - missing/ambiguous profile assignment
  - profile mode consistency
  - volatility feature id mismatch

3. Phase 3 runtime evaluators
- Added `compute_volatility_adjusted_fraction(...)`.
- Added `evaluate_adaptive_horizon_action(...)`.
- Added `evaluate_severe_loss_recovery_action(...)`.
- Preserved existing admission risk gates and exposure enforcement behavior.

4. Planner/runtime integration
- Replay planner now:
  - applies volatility-adjusted entry sizing
  - applies adaptive horizon + severe-loss action routing
  - emits one `DECISION_TRACE` risk event per signal with deterministic profile/sizing evidence
- Violation risk events remain emitted and deduplicated as before.

5. Validation and test wiring
- Added `docs/validations/PHASE_3_RUNTIME_VALIDATION.sql`.
- Updated `scripts/test_all.sh` to execute Phase 3 validation gate.
- Updated unit/integration fixtures and tests for new context/profile surfaces.

## Determinism/Compatibility Notes
- No append-only behavior weakened.
- No replay hash contract bypass introduced.
- Existing Phase 1D/2 invariants remain enforced.
- Decision trace payloads are serialized deterministically (sorted JSON keys).

## Remaining Follow-Up
- Phase 4 order lifecycle should consume de-risk intent for explicit partial reduction actions.
