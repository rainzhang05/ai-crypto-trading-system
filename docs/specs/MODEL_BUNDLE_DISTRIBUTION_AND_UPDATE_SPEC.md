# AI CRYPTO TRADING SYSTEM
## MODEL BUNDLE DISTRIBUTION AND UPDATE SPECIFICATION
Version: 1.1
Status: AUTHORITATIVE (FUTURE DELIVERY REQUIREMENTS)
Scope: Inference Artifact Packaging, GitHub Repository Distribution, Compatibility, and Update Safety

---

# 0. Purpose

Define mandatory standards for delivering trained inference artifacts to users and for safe model updates after release.

---

# 1. Distribution Policy

Primary channel:

- GitHub repository-native model registry (continuous versioned commits/tags in this repository).

Repository policy:

1. Trained model files, algorithm artifacts, and required metadata are versioned in-repo.
2. Updates are continuously pushed through governed git workflow (branch/PR/merge/tag).
3. macOS app sync path must read model/data artifacts from this repository (directly or through local runtime proxy).
4. GitHub Releases may be used as optional mirrors, but repository state is authoritative.
5. Large binary artifacts should use repository-supported large-file strategy (for example Git LFS) while preserving manifest determinism.

Default bundle scope:

- inference-ready trained model artifacts
- feature schema and preprocessing metadata
- model/version lineage metadata
- compatibility metadata

Default bundles do not require full raw training datasets.

Historical data acquisition/backfill for retraining is governed separately by:

- `docs/specs/HISTORICAL_DATA_PROVIDER_AND_CONTINUOUS_TRAINING_SPEC.md`

---

# 2. Model Bundle Manifest Contract

Each model package manifest committed to repository must include at least:

- `bundle_version`
- `model_family_versions`
- `feature_schema_hash`
- `training_lineage_metadata`
- `compatibility_range` (app/backend/model)
- artifact checksum set
- signature metadata
- source commit/tag reference
- repository path inventory of required artifacts

Manifest semantics must be deterministic and reproducible.

---

# 3. Integrity and Trust Requirements

Update/install workflow must enforce:

1. Checksum verification for all downloaded artifacts.
2. Compatibility verification against local app/backend/runtime.
3. Repository provenance verification (approved branch/tag policy).
4. Signature verification where signing metadata is provided/enforced by trust policy.

Tampered, incompatible, or unapproved-provenance artifacts must be rejected deterministically.

---

# 4. Update Installation Safety

Update process must provide:

- staging area for candidate repository snapshot/model set
- atomic install swap
- rollback-on-failure to last known good model set
- deterministic audit trail of sync/update attempts and outcomes

No partial install may become active.

---

# 5. User Experience Requirements

Desktop app must provide:

- one-click check/apply sync path from GitHub repository
- clear version and compatibility visibility
- clear failure reason messaging on rejection
- rollback status visibility when fallback occurs

Users should not need to rebuild project code to receive updated in-repo model artifacts.

---

# 6. Lifecycle and Retention

Local system must retain:

- current active model set synced from repository
- previous known-good model set (minimum one rollback point)
- update logs with timestamps and validation outcomes

Retention windows and cleanup policy must be documented.

---

# 7. Acceptance Criteria

Implementation is compliant only when:

1. Users receive trained inference artifacts on first install (no empty-model start).
2. macOS app can retrieve governed model/data artifacts from the GitHub repository sync channel.
3. Artifacts are checksum/provenance verified before activation.
4. Incompatible or unapproved artifacts are blocked before runtime activation.
5. Failed sync/update automatically rolls back to prior working model set.
6. Update workflows are auditable and deterministic.

---

END OF MODEL BUNDLE DISTRIBUTION AND UPDATE SPECIFICATION
