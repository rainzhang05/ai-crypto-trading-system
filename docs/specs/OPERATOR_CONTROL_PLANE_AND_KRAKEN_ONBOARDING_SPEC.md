# AI CRYPTO TRADING SYSTEM
## OPERATOR CONTROL PLANE & KRAKEN ONBOARDING SPECIFICATION
Version: 1.1
Status: AUTHORITATIVE (FUTURE DELIVERY REQUIREMENTS)
Scope: macOS Desktop Frontend, Operator UX, and Exchange Connection Onboarding

---

# 0. Purpose

Define the mandatory user-facing control and observability surfaces required for safe operation of the trading system, and define the easiest secure path for users to connect their own Kraken account.

---

# 1. Scope

This specification governs:

- Operator frontend requirements
- Control-plane API behavior boundaries
- Kraken account connection onboarding UX
- Credential safety and governance constraints

This specification is binding with:

- `docs/specs/PROJECT_GOVERNANCE.md`
- `docs/specs/PROJECT_ROADMAP.md`
- `docs/specs/TRADING_LOGIC_EXECUTION_SPEC.md`
- `docs/specs/RISK_RULES.md`
- `docs/specs/LOCAL_FIRST_RUNTIME_AND_PRIVACY_SPEC.md`
- `docs/specs/MODEL_BUNDLE_DISTRIBUTION_AND_UPDATE_SPEC.md`

---

# 2. Operator Frontend (Required Surfaces)

Primary client target:

- macOS desktop app (SwiftUI) as first shipping control surface.

The frontend must provide:

1. Settings Control
- Governed profile selection/editing for strategy/risk settings.
- Visible bounds and validation feedback for configurable values.
- Global exposure cap policy editing.
- Per-quote-currency cap editing for `CAD`, `USD`, and `USDC`.

2. Runtime Status
- Mode (`BACKTEST` / `PAPER` / `LIVE`)
- Health/liveness state
- Kill-switch and risk-gate state
- Last successful decision/execution timestamp

3. Decision and Prediction Visibility
- Decision timeline with reason codes
- Prediction context snapshots used for decisions
- Action status (accepted/rejected/de-risk/exit)

4. Portfolio and Asset Visibility
- Current holdings and lot inventory
- Realized and unrealized PnL surfaces
- Per-asset charting (price + position + action overlays)

5. Audit Navigation
- Links to replay/validation evidence for displayed actions
- Traceability from UI row to deterministic runtime artifacts

6. Runtime Controls
- Explicit `Start` and `Stop` controls for local runtime daemon.
- Pre-live risk warning modal with explicit user confirmation.
- Paper-first gate status and live-eligibility status.

---

# 2A. Local Control API Contract (Consumed by Frontend)

Required local daemon endpoints:

- `POST /onboarding/kraken/validate`
- `POST /onboarding/kraken/connect`
- `GET /onboarding/kraken/status`
- `POST /runtime/start`
- `POST /runtime/stop`
- `GET /runtime/status`
- `GET /portfolio/summary`
- `GET /portfolio/assets`
- `GET /decisions/timeline`
- `GET /predictions/latest`
- `POST /risk/profile/update`

Control API constraints:

- loopback-only network binding by default
- authenticated local control session required
- endpoints must preserve deterministic audit event emission

---

# 3. Control-Plane Safety Constraints

The control plane must never:

- bypass runtime risk gates
- bypass schema constraints
- write directly to execution tables from frontend code paths

All settings writes must:

- flow through governed backend APIs
- be versioned
- include actor attribution and timestamp
- be replay-auditable

---

# 4. Kraken Onboarding (Easiest Safe Path)

The onboarding flow must be simple and guided:

1. Guided Setup
- User selects target mode (`PAPER` default; `LIVE` optional).
- UI provides explicit Kraken key creation instructions.

2. Permission Validation
- Enforce minimum required API scopes.
- Enforce no-withdrawal policy for trading keys.

3. Secure Credential Capture
- One-time key/secret submission.
- Secrets are never re-displayed in plaintext.
- Secrets are stored in approved secure secret storage paths only (macOS Keychain for macOS target).

4. Connectivity Verification
- Verify account reachability and required endpoints.
- Validate permissions and readiness before enablement.

5. Live Enable Confirmation
- Require explicit final confirmation to grant live order authority.
- Present safety summary before confirmation.
- Require successful paper-trial completion before first live authorization.

---

# 5. Delivery Alignment (Roadmap Binding)

Roadmap alignment:

- Phase 8A: Kraken onboarding + credential gateway
- Phase 8B: local runtime service + control API
- Phase 9A: operator control-plane capabilities
- Phase 9B: macOS packaging and first-run UX
- Phase 9C: budget and limit extensions
- Phase 10A: model-bundle updater integration

Phase completion for these slices requires:

- implemented UI/API surfaces
- deterministic audit traceability
- no-risk-bypass guarantees
- end-to-end onboarding verification in test and runbooks

---

# 6. Acceptance Criteria

Implementation is compliant only when:

1. Users can configure governed risk/strategy settings through frontend controls.
2. Users can observe current bot status, decisions/predictions, holdings, and asset charts.
3. Users can connect Kraken accounts through a guided, low-friction, policy-compliant flow.
4. Credential handling remains secure and non-plaintext in logs/artifacts.
5. Live enablement requires explicit user confirmation after successful validation checks.
6. First-time live enablement is blocked until paper-trial completion criteria are satisfied.

---

END OF OPERATOR CONTROL PLANE & KRAKEN ONBOARDING SPECIFICATION
