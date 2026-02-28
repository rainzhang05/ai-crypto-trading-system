# Quantitative Crypto Trading System
**All Models Active | Governance-Controlled | Capital Preservation First**

---

## 1. Overview

The AI Crypto Trading System is a production-grade, fully quantitative cryptocurrency trading engine designed to operate on Kraken Spot markets.

This system:

- Uses strictly market data (no LLM-driven trading decisions)
- Runs hourly prediction cycles
- Uses ensemble machine learning (tree-based + deep learning models)
- Enforces strict capital preservation rules
- Maintains deterministic and auditable logic
- Is built for long-term scalability and commercialization

The architecture is designed from inception to support:

- Deterministic behavior
- Risk-first execution
- Modular expansion
- Multi-model ensemble stacking
- Full traceability and reproducibility

This is not an experimental trading bot.  
It is a governed quantitative trading system.

---

## 2. Trading Constraints

- Exchange: Kraken Spot
- No leverage
- No margin
- No borrowing
- Long-only spot positions
- Maximum concurrent positions: 10
- Maximum total portfolio exposure: 20%
- Hard maximum drawdown: 20%

Trading fee modeled:

- 0.4% per trade
- 0.8% round-trip

All trades must exceed transaction costs before execution.

---

## 3. Model Architecture

All models are active from initial deployment.

### 3.1 Tree-Based Models

- XGBoost
- LightGBM
- Random Forest

Purpose:
Capture nonlinear relationships in tabular engineered features.

### 3.2 Deep Learning Models

- LSTM
- Transformer

Purpose:
Capture sequential temporal patterns in price movement.

### 3.3 Regime Classifier

Identifies:

- Trending regime
- Range regime
- High-volatility regime
- Crash regime

### 3.4 Meta-Learner

Stacking ensemble that combines:

- Tree-based model outputs
- Deep model outputs
- Regime state

Final trade decisions are derived exclusively from meta-learner output.

---

## 4. Feature Engineering

Features include:

- Momentum (1h, 4h, 24h returns)
- Rolling momentum slope
- ATR (14)
- Rolling standard deviation
- Volatility regime flags
- Volume surge ratios
- Spread widening indicators
- Breakout detection
- Mean reversion distance
- BTC beta
- Rolling correlation to BTC
- Market breadth indicators

All features:

- Are timestamp-aligned
- Use strictly historical data
- Avoid forward-looking bias
- Are deterministic and reproducible

---

## 5. Risk Management

Capital preservation is the highest priority.

### 5.1 Position Sizing

Base Risk Fraction: 2% of Portfolio Value  
Position sizing is volatility-adjusted.

### 5.2 Drawdown Controls

- 10% drawdown → reduce risk
- 15% drawdown → reduce exposure
- 20% drawdown → immediate halt

### 5.3 Exposure Limits

- Maximum 10 concurrent positions
- Maximum total exposure: 20%
- Correlation cluster caps enforced

### 5.4 Kill Switch

Triggers include:

- Exchange API instability
- Spread anomalies
- Volatility spikes
- Data integrity failures

Kill switch prevents new entries and requires manual reactivation.

---

## 6. Backtesting

Backtesting must:

- Use hourly data
- Include full fee modeling
- Include slippage modeling
- Enforce drawdown logic
- Enforce exposure caps
- Use walk-forward validation
- Avoid static train/test splits
- Avoid lookahead bias

Backtest logic must match live trading logic exactly.

---

# 7. Infrastructure (Google Cloud Platform)

Cloud Provider: **Google Cloud Platform (GCP)**

Core Components:

- **Cloud Run** – Containerized backend deployment
- **Cloud SQL (PostgreSQL)** – Primary database
- **Cloud Storage (GCS)** – Raw data & model artifact storage
- **Artifact Registry** – Docker image registry
- **Secret Manager** – API key management
- **Cloud Scheduler** – Hourly execution trigger
- **Cloud Logging & Monitoring** – Observability layer

Containerization: Docker  
Version Control: GitHub  
CI/CD: GitHub Actions → GCP Deployment  
Backend: FastAPI  
Frontend: Next.js  

All logs must allow full reconstruction of any trading hour.

---

## 8. Governance Structure

This system operates under strict governance.

Governance files are located in: **/governance**


Includes:

- PROJECT_GOVERNANCE.md
- ARCHITECT_DECISIONS.md
- MODEL_ASSUMPTIONS.md
- RISK_RULES.md
- ARCHITECT_PROMPT.md
- IMPLEMENTATION_PROMPT.md
- AUDITOR_PROMPT.md

No structural change is valid unless logged and reviewed.

---

## 9. Tri-Agent Development Method

This project uses a structured three-agent development framework.

### 9.1 Architect Agent

Role:

- Enforces master specification
- Defines module contracts
- Prevents architectural drift
- Reviews all structural changes
- Protects deterministic logic

Reasoning Level: Extra High  
Environment: Local

Does not write large production code.

---

### 9.2 Implementation Agent

Role:

- Writes code
- Implements defined contracts
- Adds logging and error handling
- Maintains modular structure

Reasoning Level: High  
Environment: Cloud or Local

Does not modify architecture.

---

### 9.3 Auditor Agent

Role:

- Searches for financial errors
- Detects lookahead bias
- Verifies fee modeling
- Verifies slippage modeling
- Validates risk enforcement
- Checks capital accounting

Reasoning Level: Extra High  
Environment: Local

Assumes bugs exist until proven safe.

---

## 10. Development Cycle

Every module follows this sequence:

1. Architect defines contract.
2. Implementation writes code.
3. Architect reviews compliance.
4. Auditor verifies financial correctness.
5. Merge only after approval.

System prompts must be applied at the beginning of each new agent session.

Role mixing is prohibited.

---

## 11. Version Control Rules

- All changes committed via Git
- Commit messages must describe financial impact
- Structural changes logged in ARCHITECT_DECISIONS.md
- Model versions tracked in MLflow

---

## 12. Production Readiness Requirements

Before live trading:

- Minimum 30 days paper trading
- Drawdown enforcement verified
- Kill switch tested
- Fee modeling validated
- Slippage model validated
- Risk engine tested under stress

Live deployment begins with minimal capital allocation.

---

## 13. Priority Order

When conflicts arise:

1. Capital Preservation
2. Deterministic Behavior
3. Risk Enforcement
4. Backtest Integrity
5. Performance Optimization

No optimization may weaken capital protection.
