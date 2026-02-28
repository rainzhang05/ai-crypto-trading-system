# AI CRYPTO TRADING SYSTEM
## MASTER TECHNICAL ARCHITECTURE & PRODUCTION SPECIFICATION
### Quantitative Core – All Models Active
### Google Cloud Platform Deployment

---

# 1. Executive Overview

This document defines the complete production-grade architecture for the AI Crypto Trading System.

The system:

- Operates on Kraken Spot markets
- Uses strictly quantitative market data
- Employs ensemble machine learning (tree-based + deep learning)
- Runs hourly prediction cycles
- Enforces strict capital preservation rules
- Is built for eventual commercialization

This version excludes LLM-driven trading logic.

Primary Objective:

Generate consistent risk-adjusted returns while maintaining strict capital preservation and a maximum portfolio drawdown of 20%.

---

# 2. Trading Environment & Constraints

Exchange: Kraken Spot  
No leverage  
No margin  
No borrowing  
Long-only spot positions  

Order Execution:
- Limit-first logic
- Controlled fallback to market orders

Trading Fee:
- 0.4% per trade
- 0.8% round-trip

Limits:
- Maximum concurrent positions: 10
- Maximum total portfolio exposure: 20%
- Hard maximum drawdown: 20%

---

# 3. Asset Universe

Tradable assets must:

- Be listed on Kraken
- Pass liquidity filters
- Exclude stablecoins
- Exclude meme coins
- Exclude low-liquidity assets

Liquidity Filters:
- Minimum daily volume threshold
- Maximum bid-ask spread threshold

Risk Controls:
- 30-day rolling correlation matrix
- Cluster-based exposure caps
- BTC beta monitoring

---

# 4. Infrastructure & DevOps (Google Cloud Platform)

Cloud Provider: Google Cloud Platform (GCP)

Core Components:

- Cloud Run – Backend container deployment
- Cloud SQL (PostgreSQL) – Primary database
- Cloud Storage (GCS) – Raw data and model artifacts
- Artifact Registry – Docker image storage
- Secret Manager – Secure API key storage
- Cloud Scheduler – Hourly execution trigger
- Cloud Logging – Centralized logs
- Cloud Monitoring – Observability

Containerization: Docker  
Version Control: GitHub  
CI/CD: GitHub Actions → GCP deployment  
Model Registry: MLflow  

All secrets must be stored in Secret Manager.

No credentials may be hardcoded.

---

# 5. Data Sources

Primary Market Data:
- Kraken API

Supplementary Reference Data:
- Binance (informational only)
- Coinbase (informational only)

All data must:
- Be timestamp-aligned
- Be stored raw before transformation
- Avoid forward-looking bias

Minimum historical window:
- 1 year minimum
- Preferred 3 years

---

# 6. Feature Engineering Framework

All features must be deterministic and reproducible.

## Momentum Features
- 1h return
- 4h return
- 24h return
- Rolling momentum slope

## Volatility Features
- ATR (14)
- Rolling standard deviation
- Volatility regime flag

## Liquidity Features
- Volume surge ratio
- Spread widening indicator

## Market Structure
- Breakout detection
- Mean reversion distance
- Higher high / lower low flags

## Cross-Asset Metrics
- BTC beta
- Rolling correlation to BTC
- Market breadth signal

No feature may use future information.

---

# 7. Model Architecture

All models active from deployment.

## 7.1 Tree-Based Models
- XGBoost
- LightGBM
- Random Forest

## 7.2 Deep Learning Models
- LSTM
- Transformer

## 7.3 Regime Classifier
Classifies:
- Trending
- Range
- High-volatility
- Crash regimes

## 7.4 Meta-Learner
Stacking ensemble combining:
- Tree outputs
- Deep model outputs
- Regime state

Final trade decisions derived exclusively from meta-learner output.

---

# 8. Prediction Framework

Prediction Horizons:
- 1 hour
- 4 hours
- 24 hours

Primary Execution Cycle:
- Hourly

Outputs per asset:
- Probability of upward movement
- Expected return

All predictions must be logged.

---

# 9. Strategy Engine

Entry Conditions:
- Confidence threshold met
- Expected return > fee + slippage
- Risk constraints satisfied

Exit Conditions:
- Stop-loss triggered
- Take-profit reached
- Signal reversal
- Time-based exit

Position Sizing:
- Volatility-adjusted
- Base 2% of portfolio value

Cluster exposure caps enforced.

---

# 10. Risk Management Framework

## Drawdown Rules

10% drawdown:
- Reduce base risk fraction

15% drawdown:
- Reduce exposure and position count

20% drawdown:
- Immediate halt of new trades
- Manual review required

## Kill Switch Conditions

Trigger on:
- Exchange API instability
- Spread anomaly
- Volatility spike
- Data integrity failure

Kill switch prevents new entries.

---

# 11. Backtesting Engine

Backtesting must:

- Use hourly data
- Include Kraken fee modeling
- Include slippage modeling
- Enforce risk rules
- Enforce exposure caps
- Enforce drawdown logic
- Use walk-forward validation
- Avoid static train/test splits
- Avoid lookahead bias

Backtest logic must match live logic exactly.

---

# 12. Execution Engine

Must:

- Validate capital before order
- Recalculate volatility-adjusted size
- Log order attempts
- Log partial fills
- Log cancellations
- Retry failed API calls
- Reconcile portfolio state hourly

Execution must never bypass risk layer.

---

# 13. Monitoring & Dashboard

Backend:
- FastAPI

Frontend:
- Next.js

Dashboard displays:
- Portfolio value
- Open positions
- Drawdown
- Risk state
- Model outputs
- Trade history

All logs must allow full hour reconstruction.

---

# 14. Performance Targets

Target Sharpe Ratio:
1.2 – 1.8

Target Annual Return:
20% – 60%

Maximum Monthly Drawdown:
<10%

Hard Stop Drawdown:
20%

---

# 15. Commercialization Roadmap

Phase 1:
- Proprietary trading
- Verified performance logs

Phase 2:
- Multi-user support
- Authentication layer

Phase 3:
- SaaS subscription model

All commercialization requires:
- Regulatory review
- Audit trail integrity
- Performance transparency

---

# 16. Governance Enforcement

All development governed by:

- PROJECT_GOVERNANCE.md
- ARCHITECT_DECISIONS.md
- MODEL_ASSUMPTIONS.md
- RISK_RULES.md
- ARCHITECT_PROMPT.md
- IMPLEMENTATION_PROMPT.md
- AUDITOR_PROMPT.md

No structural change is valid without logging.

Capital preservation overrides optimization.

---

END OF MASTER SPECIFICATION