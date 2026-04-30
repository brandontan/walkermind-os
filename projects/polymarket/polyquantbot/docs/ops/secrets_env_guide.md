# CrusaderBot — Secrets & Environment Variable Reference

Complete reference for all environment variables. Placeholders only — no real values.

---

## Current Activation Status

**ALL THREE ACTIVATION GUARDS ARE NOT SET IN CURRENT DEPLOYMENT:**

| Guard | Status |
|---|---|
| `EXECUTION_PATH_VALIDATED` | NOT SET |
| `CAPITAL_MODE_CONFIRMED` | NOT SET |
| `ENABLE_LIVE_TRADING` | NOT SET |

No live-trading or production-capital readiness is claimed until all three are explicitly activated.

---

## Required Variables

### Database

| Variable | Description | Example |
|---|---|---|
| `DB_DSN` | PostgreSQL DSN (read by `DatabaseClient`) | `postgresql://user:pass@host:5432/crusaderbot` |
| `CRUSADER_DB_RUNTIME_ENABLED` | Enable DB-backed surfaces at startup (`true` required for admin routes + capital confirmation) | `true` |

### Redis

| Variable | Description | Example |
|---|---|---|
| `REDIS_URL` | Redis connection string | `redis://host:6379` |

### Telegram

| Variable | Description | Example |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather | `1234567890:ABC...` |
| `TELEGRAM_CHAT_ID` | Operator Telegram chat ID (integer) — gates operator commands | `987654321` |

### Operator / Admin

| Variable | Description | Example |
|---|---|---|
| `CRUSADER_OPERATOR_API_KEY` | Token for protected `/beta/*` API routes (`X-Operator-Api-Key` header) | 32+ char random string |
| `ORCHESTRATION_ADMIN_TOKEN` | Token for `/admin/orchestration/` routes (`X-Orchestration-Admin-Token` header) | 32+ char random string |
| `SETTLEMENT_ADMIN_TOKEN` | Token for `/admin/settlement/` routes (`X-Settlement-Admin-Token` header) | 32+ char random string |

---

## Optional Variables

### Falcon (Market Signals)

| Variable | Description | Default |
|---|---|---|
| `FALCON_ENABLED` | Enable Falcon signal integration | `false` |
| `FALCON_API_KEY` | Falcon API key | — |
| `FALCON_BASE_URL` | Falcon base URL | — |
| `FALCON_TIMEOUT` | Request timeout in seconds | `30` |

If `FALCON_ENABLED=false`, the signal runner runs in stub mode (no real signals generated).

### Runtime Config

| Variable | Description | Default |
|---|---|---|
| `PORT` | HTTP server port (injected by Fly) | `8080` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `SENTRY_DSN` | Sentry error tracking DSN | — |

### Storage Paths (local mode only)

| Variable | Description | Default |
|---|---|---|
| `CRUSADER_WALLET_LINK_STORAGE_PATH` | Wallet link local storage | `/tmp/crusaderbot/runtime/wallet_links.json` |
| `CRUSADER_MULTI_USER_STORAGE_PATH` | Multi-user store local storage | `/tmp/crusaderbot/runtime/multi_user.json` |

---

## Activation Sequence (Capital Mode)

These three guards control the transition from paper trading to live capital deployment. They must be set in order and require explicit WARP🔹CMD + Mr. Walker authorization before any step.

### Step 1 — EXECUTION_PATH_VALIDATED

Confirms the real CLOB execution path has been validated and is safe to enable.

```bash
fly secrets set EXECUTION_PATH_VALIDATED=true -a crusaderbot && fly deploy --strategy immediate
```

This is a prerequisite for `CAPITAL_MODE_CONFIRMED`.

### Step 2 — CAPITAL_MODE_CONFIRMED (two-layer gate)

Two layers are required: env var + DB receipt.

**Layer 1 — Env var:**
```bash
fly secrets set CAPITAL_MODE_CONFIRMED=true -a crusaderbot && fly deploy --strategy immediate
```

**Layer 2 — DB receipt via Telegram (must be done after deploy):**

1. Operator Telegram → `/capital_mode_confirm` (no argument)
2. Bot replies with a 16-character hex token + 60-second TTL window
3. Within 60 seconds → `/capital_mode_confirm <token>`
4. Bot replies with `confirmation_id` + `confirmed_at` — receipt persisted

Both layers required. Either missing → `LiveExecutionGuard.check_with_receipt()` refuses with `capital_mode_env_gates_missing` or `capital_mode_no_active_receipt`.

See `docs/operator_runbook.md` §9 for full procedure.

### Step 3 — ENABLE_LIVE_TRADING

Final execution authority gate. Set only after steps 1 and 2 are confirmed.

```bash
fly secrets set ENABLE_LIVE_TRADING=true -a crusaderbot && fly deploy --strategy immediate
```

---

## Revoking Capital Mode

To revoke and return to paper mode:

```bash
# Operator Telegram (immediate, single step):
/capital_mode_revoke <reason>

# If full env rollback needed:
fly secrets set CAPITAL_MODE_CONFIRMED=false -a crusaderbot && fly deploy --strategy immediate
```

See `docs/operator_runbook.md` §9.2 for revoke procedure.

---

## Security Notes

- Never commit `.env` files or any file containing real values to git
- Rotate `CRUSADER_OPERATOR_API_KEY`, `ORCHESTRATION_ADMIN_TOKEN`, and `SETTLEMENT_ADMIN_TOKEN` on any suspected exposure
- `TELEGRAM_OPERATOR_CHAT_ID` gates all `/capital_mode_confirm`, `/capital_mode_revoke`, `/halt`, `/resume`, and other operator commands — protect this value
- All secrets are set via `fly secrets set` — never hardcoded in code or config files
