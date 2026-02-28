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