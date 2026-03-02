# AI CRYPTO TRADING SYSTEM
## MODEL ASSUMPTIONS DOCUMENT

This document defines all explicit and implicit assumptions underlying the quantitative trading system.

Any assumption change must be reviewed and logged in ARCHITECT_DECISIONS.md.

---

# 1. MARKET ASSUMPTIONS

1.1 Crypto markets are partially inefficient across adaptive horizons, from short-term to long-term windows.

1.2 Price movements exhibit:
- Momentum persistence in trending regimes.
- Mean reversion in range regimes.
- Volatility clustering.

1.3 Liquidity is sufficient for:
- Limit order execution.
- Small capital deployment.
- Profile-configured concurrent position limits (default 10).

1.4 Kraken order execution latency is assumed to be within normal exchange ranges and does not systematically distort continuous live predictions.

1.5 Holding duration is model-adaptive and may extend beyond 24 hours when updated forecasts preserve positive edge under risk constraints.

1.6 Slippage is non-zero and must be modeled.

1.7 Tactical short-term reversals can be harvested inside a broader campaign thesis through partial exits and re-entries.

---

# 2. DATA ASSUMPTIONS

2.1 All market data used for prediction is available at prediction timestamp.

2.2 Exchange APIs do not introduce forward-looking bias.

2.3 Data gaps may occur and must be handled explicitly.

2.4 OHLCV data accurately reflects tradable prices.

2.5 Bid-ask spread data approximates slippage when combined with volatility scaling.

2.6 Cross-exchange data (Binance, Coinbase) is informational only and does not imply tradability on those exchanges.

2.7 Full available-history ingestion from external data providers is required for governed training universes; unavailable intervals must be explicitly logged as coverage gaps (never silently imputed).

---

# 3. FEATURE ENGINEERING ASSUMPTIONS

3.1 All features must be computable using past and current information only.

3.2 Feature normalization must not use future data.

3.3 Rolling windows must use strictly historical values.

3.4 Feature engineering must be deterministic and reproducible.

3.5 Volatility (ATR, rolling std) is assumed to approximate near-term risk and support adaptive exit timing updates.

3.6 BTC beta and correlation are assumed to capture systemic crypto risk.

---

# 4. MODELING ASSUMPTIONS

4.1 Tree-based models capture nonlinear tabular relationships.

4.2 LSTM and Transformer models capture sequential temporal dependencies.

4.3 Stacking improves predictive stability over single-model approaches.

4.4 Model performance may degrade under new regimes.

4.5 Walk-forward validation reduces overfitting.

4.6 Feature importance ranking can identify redundant signals.

4.7 Model outputs must represent probability estimates, not raw arbitrary scores.

---

# 5. TRAINING ASSUMPTIONS

5.1 Historical relationships partially generalize to near-future windows.

5.2 Retraining cadence may be scheduled and/or drift-triggered and must match regime change frequency.

5.3 Overfitting risk increases with:
- Excessive feature count.
- Excessive hyperparameter tuning.
- Insufficient validation separation.

5.4 Hyperparameter tuning must not be optimized for a single backtest window.

---

# 6. RISK ASSUMPTIONS

6.1 Volatility-adjusted sizing reduces drawdown severity.

6.2 Correlated assets amplify systemic risk.

6.3 Drawdown control mechanisms reduce long-term ruin probability.

6.4 Stop-loss logic must function in live trading conditions.

6.5 Market crashes may exceed modeled slippage.

6.6 Capital preservation overrides signal confidence.

6.7 In severe loss states, rebound-vs-continuation inference is assumed to improve liquidation timing relative to naive threshold-only exits.

---

# 7. BACKTEST ASSUMPTIONS

7.1 Backtest execution approximates live trading but is not identical.

7.2 Fee and slippage modeling are approximations, not perfect representations.

7.3 Backtest does not simulate extreme black swan liquidity collapse.

7.4 Backtest performance is indicative, not guaranteed.

7.5 Execution delay between signal generation and trade placement is non-zero.

---

# 8. LIMITATIONS

The system does NOT assume:

- Perfect liquidity.
- Perfect fills.
- Constant volatility.
- Stationary statistical relationships.
- Guaranteed regime stability.
- Unlimited scaling capacity.

---

# 9. FAILURE MODES

The system may fail under:

- Structural regime shift.
- Extreme exchange outage.
- Prolonged sideways chop.
- Sudden liquidity collapse.
- Model drift.
- Incorrect slippage estimation.
- Feature leakage.

These risks must be monitored continuously.

---

# 10. ASSUMPTION CHANGE POLICY

If any assumption is invalidated:

1. Pause model retraining.
2. Evaluate impact.
3. Document in ARCHITECT_DECISIONS.md.
4. Revalidate backtest integrity.
5. Approve before resuming live trading.

---

END OF MODEL ASSUMPTIONS DOCUMENT
