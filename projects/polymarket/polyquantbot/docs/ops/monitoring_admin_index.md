# CrusaderBot — Monitoring & Admin Surface Index

Date: 2026-05-01 Asia/Jakarta  
Lane: `WARP/p9-monitoring-admin-surfaces`  
Scope: Priority 9 Lane 3 — monitoring/admin visibility only  
Mode: Paper beta / operator visibility  
Activation truth: no live-trading or production-capital readiness claim

---

## 1. Current Posture

CrusaderBot is public-paper-beta oriented. The runtime has paper-trading, portfolio, wallet orchestration, settlement/retry/reconciliation, capital-readiness gates, and operator/admin visibility surfaces.

The following activation guards remain unset in the current repo-truth posture:

| Guard | Current posture |
|---|---|
| `EXECUTION_PATH_VALIDATED` | NOT SET |
| `CAPITAL_MODE_CONFIRMED` | NOT SET |
| `ENABLE_LIVE_TRADING` | NOT SET |

This index is an operator/navigation aid. It does not activate live trading, does not create secrets, and does not claim production-capital readiness.

---

## 2. Public / No-Auth Runtime Checks

| Surface | Method | Purpose | Expected use |
|---|---:|---|---|
| `/health` | GET | Process health | Liveness check, uptime monitor |
| `/ready` | GET | Readiness + dependency posture | Release smoke, deployment check |
| `/beta/status` | GET | Paper-beta state and guard posture | Public/admin status verification |

Operator note: `healthy` is not the same as live-capital-ready. Use the capital and readiness surfaces before making any activation decision.

---

## 3. Operator-Protected Admin Surfaces

These surfaces require configured operator/admin tokens. They are intended for Mr. Walker / authorized operator usage only.

### Beta / Capital Admin

Header: `X-Operator-Api-Key: <CRUSADER_OPERATOR_API_KEY>`

| Surface | Method | Purpose |
|---|---:|---|
| `/beta/admin` | GET | Managed beta admin view + exit criteria |
| `/beta/capital_status` | GET | Capital-mode gate posture |
| `/beta/capital_mode_confirm` | POST | Two-step confirmation flow |
| `/beta/capital_mode_revoke` | POST | Revoke DB capital-mode receipt |

### Orchestration Admin

Header: `X-Orchestration-Admin-Token: <ORCHESTRATION_ADMIN_TOKEN>`

| Surface | Method | Purpose |
|---|---:|---|
| `/admin/orchestration/wallets` | GET | All-wallet orchestration state snapshot |
| `/admin/orchestration/wallets/{wallet_id}` | GET | Per-wallet health/status |
| `/admin/orchestration/wallets/{wallet_id}/enable` | POST | Enable wallet |
| `/admin/orchestration/wallets/{wallet_id}/disable` | POST | Disable wallet |
| `/admin/orchestration/halt` | POST | Global halt |
| `/admin/orchestration/halt` | DELETE | Clear global halt / resume |

### Settlement Admin

Header: `X-Settlement-Admin-Token: <SETTLEMENT_ADMIN_TOKEN>`

| Surface | Method | Purpose |
|---|---:|---|
| `/admin/settlement/status/{workflow_id}` | GET | Settlement workflow status |
| `/admin/settlement/retry/{workflow_id}` | GET | Retry state |
| `/admin/settlement/failed-batches` | GET | Failed batch visibility |
| `/admin/settlement/intervene` | POST | Force operator intervention |

---

## 4. Telegram Operator Surfaces

Operator Telegram commands remain restricted to the configured operator chat.

| Area | Commands |
|---|---|
| Status | `/status`, `/capital_status`, `/wallets` |
| Paper portfolio | `/positions`, `/pnl`, `/risk` |
| Worker safety | `/kill`, `/halt`, `/resume` |
| Wallet orchestration | `/wallet_enable <wallet_id>`, `/wallet_disable <wallet_id>` |
| Settlement | `/settlement_status <workflow_id>`, `/retry_status <workflow_id>`, `/failed_batches`, `/settlement_intervene` |
| Capital ceremony | `/capital_mode_confirm`, `/capital_mode_confirm <token>`, `/capital_mode_revoke <reason>` |

---

## 5. Minimum Monitor Checklist

Before any public-paper-beta announcement, verify:

- `/health` returns process alive.
- `/ready` returns expected readiness posture.
- `/beta/status` preserves paper-only / guard truth.
- `/beta/capital_status` confirms capital-mode gates are still off unless explicitly authorized.
- Telegram `/status` replies with non-empty status.
- Telegram `/capital_status` reports guard posture truthfully.
- Operator-only routes reject missing/invalid tokens.
- Emergency commands are known and documented: `/kill`, `/halt`, `/resume`, `/capital_mode_revoke`.

---

## 6. Evidence to Capture

Store evidence in the relevant FORGE/SENTINEL/BRIEFER report path when running validation:

| Evidence | Suggested capture |
|---|---|
| HTTP status checks | Command output or logs for `/health`, `/ready`, `/beta/status` |
| Operator auth check | 401/403 for missing token, success for authorized token |
| Telegram operator status | Screenshot/log of `/status` and `/capital_status` replies |
| Guard posture | `/beta/capital_status` output with all gates shown |
| Emergency rehearsal | Operator checklist confirmation, not live incident execution |

---

## 7. Non-Goals

This lane does not:

- change runtime code,
- deploy a new environment,
- create or rotate secrets,
- execute live trades,
- enable capital mode,
- claim production-capital readiness,
- replace the full operator runbook.

For fast operation, use `docs/ops/operator_checklist.md`. For release-state visibility, use `docs/release_dashboard.md`.
