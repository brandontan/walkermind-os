# CrusaderBot — Operator Quick Reference

One-page reference for key operator commands. For full procedures, see `docs/operator_runbook.md`.

---

## Telegram Operator Commands

All commands gated to `TELEGRAM_CHAT_ID`. Non-operator users cannot invoke these.

### Status & Monitoring

| Command | Description |
|---|---|
| `/status` | System status: mode, guards, worker state |
| `/capital_status` | Capital mode gate status: env vars + DB receipt state |
| `/wallets` | Active wallet list + enable/disable status |

### Paper Trading

| Command | Description |
|---|---|
| `/positions` | Current open paper positions |
| `/pnl` | Full PnL breakdown |
| `/risk` | Live risk gate state |

### Worker Control

| Command | Description |
|---|---|
| `/kill` | **Emergency kill switch** — sets kill switch + forces autotrade off (requires server restart to clear) |
| `/halt` | Global orchestration halt — blocks all wallet routing |
| `/resume` | Clear orchestration halt only (does NOT clear kill switch) |

### Settlement

| Command | Description |
|---|---|
| `/settlement_status <workflow_id>` | Settlement engine status for workflow |
| `/retry_status <workflow_id>` | Retry queue state for workflow |
| `/failed_batches` | Failed batch list (note: always returns [] in current build — see known issues) |
| `/settlement_intervene` | Force operator intervention on settlement |

### Wallet Orchestration

| Command | Description |
|---|---|
| `/wallet_enable <wallet_id>` | Enable a specific wallet for orchestration |
| `/wallet_disable <wallet_id>` | Disable a specific wallet |

### Capital Mode (authorized operators only)

| Command | Description |
|---|---|
| `/capital_mode_confirm` | Start two-step confirmation (step 1/2 — no argument) |
| `/capital_mode_confirm <token>` | Complete confirmation (step 2/2 — within 60s TTL) |
| `/capital_mode_revoke <reason>` | Immediately revoke capital mode DB receipt |

---

## FastAPI Admin Routes

Require `CRUSADER_OPERATOR_API_KEY` header (`X-Operator-Api-Key`):

| Route | Method | Description |
|---|---|---|
| `/health` | GET | Health check (no auth) |
| `/ready` | GET | Readiness check + env summary (no auth) |
| `/beta/status` | GET | Beta system status + guard state |
| `/beta/admin` | GET | Managed-beta admin surface + exit criteria |
| `/beta/capital_status` | GET | Capital mode gate status |
| `/beta/capital_mode_confirm` | POST | Step 1: issue token |
| `/beta/capital_mode_confirm` | POST | Step 2: commit with token |
| `/beta/capital_mode_revoke` | POST | Revoke DB receipt |

Require `ORCHESTRATION_ADMIN_TOKEN` header (`X-Orchestration-Admin-Token`):

| Route | Method | Description |
|---|---|---|
| `/admin/orchestration/wallets` | GET | All wallets state snapshot |
| `/admin/orchestration/wallets/{wallet_id}` | GET | Per-wallet health status |
| `/admin/orchestration/wallets/{wallet_id}/enable` | POST | Enable specific wallet |
| `/admin/orchestration/wallets/{wallet_id}/disable` | POST | Disable specific wallet |
| `/admin/orchestration/halt` | POST | Set global halt |
| `/admin/orchestration/halt` | DELETE | Clear global halt (resume) |

Settlement admin (require `SETTLEMENT_ADMIN_TOKEN` header `X-Settlement-Admin-Token`):

| Route | Method | Description |
|---|---|---|
| `/admin/settlement/status/{workflow_id}` | GET | Settlement engine status |
| `/admin/settlement/retry/{workflow_id}` | GET | Retry status for workflow |
| `/admin/settlement/failed-batches` | GET | Failed batch list |
| `/admin/settlement/intervene` | POST | Force operator intervention |

---

## Emergency Procedures

### Activate kill switch

```
Telegram: /kill
```

Sets the beta kill switch and forces autotrade off. This is **not reversible via Telegram** — the kill switch state is in-memory and only clears on server restart. Use `/halt` + `/resume` for reversible orchestration pausing.

### Revoke capital mode (if live)

```
Telegram: /capital_mode_revoke <reason>
```

Single step — immediate. Subsequent live-execution calls refuse with `capital_mode_no_active_receipt`.

For env-level rollback:
```bash
fly secrets set CAPITAL_MODE_CONFIRMED=false -a crusaderbot && fly deploy --strategy immediate
```

### Check logs

```bash
fly logs -a crusaderbot

# Filter for critical events:
fly logs -a crusaderbot | grep -E "CRITICAL|capital_mode_guard_blocked|live_execution_guard_blocked|kill_switch"
```

### Rollback deployment

```bash
fly releases list -a crusaderbot
fly deploy --image <previous-image-ref> -a crusaderbot --strategy immediate
```

---

## Risk Constants (fixed — never override in code or config)

| Rule | Value |
|---|---|
| Kelly fraction (α) | 0.25 — fractional only |
| Max position size | <= 10% of total capital |
| Daily loss limit | -$2,000 hard stop |
| Max drawdown | > 8% — auto-halt |
| Min orderbook depth | $10,000 |
| Kill switch | Telegram `/kill` — immediate halt |

---

## Key Log Events

| Event | Level | Meaning |
|---|---|---|
| `capital_mode_guard_blocked` | CRITICAL | Live execution attempted with guards off |
| `live_execution_guard_blocked` | WARNING | Guard refusal — check reason field |
| `capital_mode_confirm_attempt` | INFO/WARNING | Confirmation step attempt |
| `capital_mode_revoke_attempt` | INFO/WARNING | Revoke attempt |
| `kill_switch_activated` | CRITICAL | Worker killed |
| `orchestration_halted` | WARNING | Global halt active |
| `settlement_alert_critical` | CRITICAL | Settlement drift or failure |

Full reference: `docs/operator_runbook.md`
