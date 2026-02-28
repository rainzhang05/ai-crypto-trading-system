# AI CRYPTO TRADING SYSTEM
## PROJECT GOVERNANCE DOCUMENT

This document defines the non-negotiable architectural, financial, and operational rules governing the development of the AI Crypto Trading System.

This system manages real capital.  
Stability, determinism, and capital preservation take precedence over optimization and speed.

All AI agents, developers, and contributors must comply with the rules defined herein.

---

# 1. GOVERNING PRINCIPLES

1. The system must remain deterministic.
2. All trading decisions must be fully backtestable.
3. No non-quantitative discretionary logic is allowed.
4. Capital preservation has priority over return maximization.
5. The 20% maximum drawdown rule is absolute and cannot be modified without explicit architectural revision.
6. No hidden leverage is permitted.
7. No margin, borrowing, or synthetic leverage is allowed.
8. All risk controls must be enforced at execution time.

---

# 2. ARCHITECTURAL IMMUTABILITY RULES

The following components are architecture-critical and cannot be modified without Architect approval:

- Position sizing formula
- Fee modeling logic
- Slippage modeling logic
- Walk-forward validation structure
- Timestamp alignment logic
- Meta-learner structure
- Drawdown halting rules
- Correlation cluster caps
- Execution order logic

Any proposed modification must include:

- Reason for change
- Risk impact analysis
- Backtest impact analysis
- Explicit approval documentation

---

# 3. DATA GOVERNANCE RULES

1. All data must be timestamped.
2. No forward-looking data is allowed in feature construction.
3. No label leakage is permitted.
4. All features must be derived only from information available at prediction time.
5. Timezone consistency must be enforced across all exchanges.
6. Market data must be stored in raw form before transformation.
7. Feature pipelines must be reproducible.

Failure to comply results in invalid backtesting.

---

# 4. MODEL GOVERNANCE RULES

All models must:

- Be trained using walk-forward validation.
- Avoid static train/test splits.
- Log hyperparameters.
- Log training window.
- Log validation performance.
- Log feature importance where applicable.
- Be reproducible using saved seeds.

No model may:

- Access future returns during training.
- Use test data in feature normalization.
- Be manually tuned to a single backtest window.

---

# 5. BACKTESTING GOVERNANCE

Backtesting must:

- Include Kraken fee of 0.4% per trade.
- Include slippage modeling.
- Enforce position limits.
- Enforce volatility-adjusted sizing.
- Enforce drawdown halting logic.
- Enforce cluster exposure caps.
- Enforce execution delays consistent with live environment.

Backtests that ignore any of the above are invalid.

---

# 6. RISK GOVERNANCE

The following are mandatory:

- 10% drawdown → reduce position size.
- 15% drawdown → reduce trade frequency.
- 20% drawdown → immediate trading halt.

The halt logic must be executed at runtime, not simulated only.

No override logic may bypass this.

---

# 7. EXECUTION GOVERNANCE

Execution engine must:

- Validate capital availability before order placement.
- Recalculate position size using current volatility.
- Verify spread before placing limit orders.
- Log all order attempts.
- Log partial fills.
- Log cancellations.
- Log final fill price.
- Retry failed API calls with exponential backoff.

Under no circumstances may:

- Orders exceed available capital.
- Orders bypass risk validation.
- Orders ignore fee assumptions.

---

# 8. CHANGE MANAGEMENT PROCESS

All structural changes must follow:

1. Architect proposal.
2. Implementation.
3. Architect review.
4. Auditor review.
5. Documented approval in ARCHITECT_DECISIONS.md.

No direct structural changes may be merged without review.

---

# 9. AGENT ROLE ENFORCEMENT

Architect Agent:
- Defines structure.
- Enforces constraints.
- Rejects architectural drift.

Implementation Agent:
- Executes strictly defined tasks.
- Does not modify architecture.

Auditor Agent:
- Searches for bias, leakage, accounting errors, and risk violations.

No agent may operate outside its defined role.

---

# 10. PROHIBITED ACTIONS

The following are strictly prohibited:

- Introducing LLM decision logic into trading layer.
- Removing drawdown halts.
- Disabling slippage modeling.
- Hardcoding profit thresholds to pass backtests.
- Overriding correlation caps.
- Skipping walk-forward validation.
- Using live trading as experimentation.

---

# 11. LOGGING REQUIREMENTS

The system must log:

- Every prediction.
- Every feature snapshot.
- Every model output.
- Every trade signal.
- Every order event.
- Every portfolio value update.
- Every drawdown state.

Logs must allow full reconstruction of any trading hour.

---

# 12. PRODUCTION SAFETY REQUIREMENTS

Before enabling live trading:

- Paper trading must run for minimum 30 days.
- Backtest must pass performance validation.
- Risk halting must be tested.
- Kill switch must be tested.
- Order retry logic must be tested.

Live trading must begin with minimal capital allocation.

---

# 13. VERSION CONTROL REQUIREMENTS

- All changes must be committed via Git.
- Commit messages must describe financial impact.
- Major architecture changes require version tagging.
- Model versions must be registered via MLflow.

---

# 14. PRIORITY ORDER

When conflicts arise, priority order is:

1. Capital Preservation
2. Deterministic Behavior
3. Risk Enforcement
4. Backtest Integrity
5. Performance Optimization

---

END OF PROJECT GOVERNANCE DOCUMENT