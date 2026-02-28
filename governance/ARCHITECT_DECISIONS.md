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

END OF ARCHITECTURAL DECISIONS LOG