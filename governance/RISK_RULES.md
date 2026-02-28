# AI CRYPTO TRADING SYSTEM
## RISK MANAGEMENT & CAPITAL CONTROL RULES

This document defines all formal capital allocation, exposure, drawdown, and halting logic.

These rules are non-negotiable.

Any modification requires logging in ARCHITECT_DECISIONS.md.

---

# 1. CAPITAL DEFINITION

1.1 Portfolio Value (PV)

PV = Available Cash + Market Value of Open Positions

1.2 Available Capital

Available Capital = Cash not locked in open orders.

1.3 Risk Capital

Risk Capital = PV × Risk Scaling Factor

Risk Scaling Factor adjusts based on drawdown state.

---

# 2. POSITION SIZING RULE

The system uses volatility-adjusted position sizing.

Base Risk Fraction = 2% of Portfolio Value.

Base Position Size = PV × 0.02

Volatility Adjustment:

Adjusted Position Size = Base Position Size × (Target Volatility / Asset Volatility)

Where:

- Asset Volatility = ATR(14) or rolling std
- Target Volatility = predefined constant benchmark

Position size must never exceed:

- 2% of PV under normal conditions
- Available Capital
- Cluster exposure cap

---

# 3. MAXIMUM EXPOSURE RULES

3.1 Maximum Concurrent Positions = 10

3.2 Maximum Total Exposure = 20% of Portfolio Value

3.3 Maximum Exposure per Correlation Cluster = 8% of Portfolio Value

3.4 Exposure must be recalculated before every order submission.

---

# 4. DRAWDOWN CALCULATION

Peak Portfolio Value (PPV) = highest historical PV.

Drawdown % = (PPV - PV) / PPV × 100

Drawdown state must be calculated hourly.

---

# 5. DRAWDOWN RESPONSE RULES

If Drawdown >= 10%:

- Reduce Base Risk Fraction from 2% to 1.5%.

If Drawdown >= 15%:

- Reduce Base Risk Fraction to 1%.
- Reduce maximum concurrent positions to 5.

If Drawdown >= 20%:

- Immediately halt all new trading.
- Cancel open unfilled orders.
- Maintain only protective exits.
- Require manual review before resuming.

This logic must execute in live runtime.

It must not rely solely on backtest simulation.

---

# 6. STOP-LOSS RULE

Each trade must define:

- Stop-loss level based on volatility multiple.
- Take-profit level based on expected return threshold.

Stop-loss must be:

- Pre-calculated before order placement.
- Stored in database.
- Enforced via runtime monitoring.

---

# 7. KILL SWITCH CONDITIONS

Immediate halt if any of the following occur:

- Exchange API failure > threshold duration.
- Spread widens beyond acceptable multiple of historical average.
- Market volatility exceeds defined extreme threshold.
- Database integrity error.
- Risk rule inconsistency detected.

Kill switch must:

- Prevent new entries.
- Log reason.
- Require manual reactivation.

---

# 8. FEE AND SLIPPAGE ENFORCEMENT

All trade profitability calculations must include:

- Kraken fee = 0.4% per trade.
- Modeled slippage component.

Order size must be adjusted to ensure:

Expected return > fee + slippage threshold.

No trade may be entered if:

Expected Return ≤ Transaction Cost.

---

# 9. CAPITAL PROTECTION PRIORITY

When conflict arises between:

- Signal confidence
- Capital protection

Capital protection wins.

No override logic may bypass risk rules.

---

# 10. LIVE VS BACKTEST CONSISTENCY

The exact same risk rules must apply in:

- Backtesting engine
- Paper trading
- Live trading

No simplified risk model is allowed in backtest.

---

# 11. SCALING RULE

Before increasing capital allocation:

- Minimum 30-day paper trading.
- Backtest validation.
- Drawdown behavior review.
- Architect approval.

Capital scaling must be gradual.

---

# 12. PROHIBITED ACTIONS

The following are forbidden:

- Increasing position size to recover losses.
- Disabling drawdown halts.
- Ignoring volatility scaling.
- Hardcoding position size.
- Ignoring correlation caps.
- Overriding kill switch.

---

END OF RISK MANAGEMENT RULES