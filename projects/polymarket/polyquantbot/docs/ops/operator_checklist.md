# CrusaderBot — Operator Checklist

Date: 2026-05-01 Asia/Jakarta  
Lane: `WARP/p9-monitoring-admin-surfaces`  
Scope: Priority 9 Lane 3 — operator checklist / admin visibility  
Mode: Paper beta only unless separately authorized

---

## 1. Hard Boundary

Do not claim live-trading readiness unless all activation gates are intentionally completed.

Current repo-truth posture:

- `EXECUTION_PATH_VALIDATED` — NOT SET
- `CAPITAL_MODE_CONFIRMED` — NOT SET
- `ENABLE_LIVE_TRADING` — NOT SET

If any surface appears to imply live trading is enabled while these guards are not set, treat it as a release blocker.

---

## 2. Pre-Run Checklist

| Check | Required result |
|---|---|
| Repo branch | Running from approved branch or `main` |
| Runtime posture | Paper beta / operator visibility |
| Secrets | Values exist only in runtime secret store, never in repo docs |
| DB migrations | `001_settlement_tables.sql` and `002_capital_mode_confirmations.sql` applied where required |
| Telegram operator chat | `TELEGRAM_CHAT_ID` points to the authorized operator chat |
| Operator tokens | `CRUSADER_OPERATOR_API_KEY`, `ORCHESTRATION_ADMIN_TOKEN`, `SETTLEMENT_ADMIN_TOKEN` configured where needed |
| Activation gates | Guard values match intended release posture |

---

## 3. Startup Smoke

Run these in order after deploy/restart.

| Step | Surface | Pass condition |
|---:|---|---|
| 1 | `/health` | Process responds successfully |
| 2 | `/ready` | Readiness response is truthful; dependency issues are explicit |
| 3 | `/beta/status` | Paper-beta status is visible and does not overclaim |
| 4 | `/beta/capital_status` | Capital guard state is visible |
| 5 | Telegram `/status` | Operator receives non-empty status |
| 6 | Telegram `/capital_status` | Guard posture matches API truth |

Stop if `/ready`, `/beta/status`, or `/capital_status` contradict the guard posture.

---

## 4. Admin Visibility Checklist

| Area | Surface | Pass condition |
|---|---|---|
| Beta admin | `/beta/admin` | Protected by operator key and returns managed beta state |
| Orchestration | `/admin/orchestration/wallets` | Protected by orchestration token and returns wallet snapshot |
| Per-wallet status | `/admin/orchestration/wallets/{wallet_id}` | Protected and returns clear available/degraded/unavailable state |
| Settlement status | `/admin/settlement/status/{workflow_id}` | Protected and returns workflow status |
| Failed batches | `/admin/settlement/failed-batches` | Protected; empty list is acceptable if explicitly represented |
| Capital status | `/beta/capital_status` | Protected where required and never hides missing gates |

---

## 5. Operator Telegram Checklist

| Command | When to use | Expected posture |
|---|---|---|
| `/status` | General runtime check | Shows runtime/paper-beta state |
| `/capital_status` | Activation guard review | Shows env + DB receipt posture |
| `/wallets` | Orchestration review | Shows active/disabled/degraded wallets |
| `/positions` | Paper position review | Shows paper positions only |
| `/pnl` | Paper PnL review | Shows realized/unrealized paper PnL |
| `/risk` | Risk posture review | Shows risk state / guard posture |
| `/halt` | Reversible orchestration pause | Blocks wallet routing |
| `/resume` | Clear reversible halt | Does not clear kill switch |
| `/kill` | Emergency stop | Immediate, not reversible via Telegram |
| `/capital_mode_revoke <reason>` | Revoke capital-mode DB receipt | Should stop capital-mode authorization |

---

## 6. Release-Decision Checklist

A paper-beta public release can proceed only when these are true:

- Public docs are current.
- Support docs list known issues truthfully.
- Operator quick reference is current.
- Monitoring/admin index is current.
- Release dashboard is current.
- Smoke checks pass.
- Guard posture is explicit.
- No live-trading or production-capital claim appears in public copy.

A capital/live release remains blocked unless Mr. Walker and WARP🔹CMD explicitly authorize the env-gate and operator receipt sequence.

---

## 7. Emergency Checklist

### Immediate paper/live safety stop

1. Telegram: `/kill`
2. Confirm `/status`
3. Check logs for `kill_switch_activated`
4. Do not resume until incident reason is documented

### Reversible orchestration pause

1. Telegram: `/halt`
2. Confirm `/wallets`
3. Resolve issue
4. Telegram: `/resume`

### Capital-mode revoke

1. Telegram: `/capital_mode_revoke <reason>`
2. Confirm `/capital_status`
3. Confirm `/beta/capital_status`
4. Capture evidence in incident report

### Deployment rollback

1. List releases.
2. Redeploy previous known-good image.
3. Run startup smoke.
4. Capture evidence.

---

## 8. Evidence Pack

For each release/incident, capture:

- timestamp,
- commit SHA,
- deployment image/release id,
- `/health`, `/ready`, `/beta/status`,
- `/beta/capital_status`,
- Telegram `/status`,
- Telegram `/capital_status`,
- operator action taken,
- result and follow-up decision.
