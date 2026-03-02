# AI CRYPTO TRADING SYSTEM
## RISK MANAGEMENT & CAPITAL CONTROL RULES
Version: 1.1
Status: AUTHORITATIVE

This document defines formal capital allocation, exposure, drawdown, and emergency-control logic.

---

# 1. PRINCIPLES

1. Capital preservation is mandatory.
2. Risk controls must be enforced at runtime before order emission.
3. Risk limits are profile-configurable in UI with governance-safe defaults.
4. Default values are not hardcoded forever; they are baseline presets.

---

# 2. CAPITAL AND RISK DEFINITIONS

- Portfolio Value (PV) = cash + market value of open positions.
- Available Capital = free cash not reserved by open orders.
- Risk Profile = versioned set of runtime risk parameters selected by user/account policy.

---

# 3. USER-CONFIGURABLE LIMITS (WITH DEFAULTS)

The following must be configurable through interface controls:

1. `max_concurrent_positions` (default `10`).
2. `max_total_exposure` with unit mode:
   - `PERCENT_OF_PV` (default `20%`).
   - `ABSOLUTE_AMOUNT` (default profile amount).
3. `max_cluster_exposure` with unit mode:
   - `PERCENT_OF_PV` (default `8%`).
   - `ABSOLUTE_AMOUNT` (default profile amount).

Runtime must enforce the active profile values, not static constants.

---

# 4. POSITION SIZING RULE

Position sizing remains volatility-aware and profile-driven.

- Base sizing starts from profile risk fraction and volatility scaling.
- Final order size is clipped by:
  - available capital
  - max total exposure (selected unit mode)
  - max cluster exposure (selected unit mode)
  - exchange/lot constraints

---

# 5. DRAWDOWN POLICY

Drawdown controls are profile-configurable tiers with default safety presets.

Default profile may include traditional tiers (for example 10/15/20), but runtime must treat these as configurable policy values rather than immutable constants.

Critical behavior:

1. Portfolio drawdown controls primarily govern admission of new risk.
2. Portfolio drawdown does not imply automatic immediate liquidation of all open positions.
3. Open positions are managed by prediction-led adaptive exit/recovery logic.

---

# 6. ENTRY AND EXIT RISK BEHAVIOR

## 6.1 Entry

Block new entry when any of the following holds:

- Active risk profile limits would be exceeded.
- Predicted downside risk is dominant.
- Liquidity/spread/market-quality checks fail.

## 6.2 Exit

Exit is prediction-led:

- Exit aggressively when outlook is strongly negative and recovery odds are weak.
- Avoid panic liquidation solely due to one loss-percentage threshold breach.
- Use partial de-risking when outlook is mixed.

---

# 7. SEVERE LOSS RECOVERY RULE

When a position is deeply adverse:

1. Enter recovery-analysis mode.
2. Re-evaluate rebound-vs-continuation outlook continuously.
3. Prefer:
   - hold if recovery outlook remains credible,
   - partial de-risk if uncertainty is high,
   - full exit only when persistent downside is strongly likely.

Exact model-state conditions and persistence logic are defined in:

- `docs/specs/TRADING_LOGIC_EXECUTION_SPEC.md`

---

# 8. KILL SWITCH

Immediate entry-block when kill switch triggers:

- Exchange/API instability
- Data integrity failure
- Extreme market-quality failure
- Internal risk consistency failure

Kill switch behavior:

- Prevent new entries
- Preserve logging and reason codes
- Require controlled reactivation

---

# 9. COST GATING

All entry profitability checks must include fee and slippage.

No entry may proceed when expected net edge after cost is insufficient under active profile policy.

---

# 10. LIVE / PAPER / BACKTEST PARITY

Risk logic must be strategy-identical across backtest, paper, and live, except for environment-specific execution frictions.

No simplified risk model is allowed in backtest.

---

# 11. PROHIBITED ACTIONS

Forbidden:

- Bypassing risk gates
- Disabling drawdown controls
- Hardcoding immutable exposure/position caps in strategy runtime
- Hardcoding universal forced hold-time exits
- Ignoring configured unit mode for exposure (percent vs amount)

---

# 12. AUDIT REQUIREMENTS

Must log per decision:

- active risk profile version and values
- exposure unit mode and computed usage
- gate pass/fail reasons
- severe-loss recovery mode actions

Logs must support deterministic replay.

---

# 13. OPERATOR FRONTEND AND KRAKEN ONBOARDING RISK REQUIREMENTS

The user-facing control plane must preserve risk enforcement guarantees:

- frontend settings changes cannot bypass server-side risk validation
- exposure/drawdown limits remain authoritative in runtime regardless of UI state
- live trading enablement must remain blocked until Kraken credential validation succeeds
- onboarding must enforce no-withdrawal trading key policy

Detailed UX/control-plane requirements are defined in:

- `docs/specs/OPERATOR_CONTROL_PLANE_AND_KRAKEN_ONBOARDING_SPEC.md`

---

END OF RISK MANAGEMENT RULES
