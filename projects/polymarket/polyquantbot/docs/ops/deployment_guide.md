# CrusaderBot — Deployment Guide (Fly.io)

Step-by-step guide for deploying CrusaderBot to Fly.io.

---

## Prerequisites

- [Fly CLI](https://fly.io/docs/getting-started/installing-flyctl/) installed and authenticated (`fly auth login`)
- PostgreSQL database provisioned (Fly Postgres recommended)
- Redis instance provisioned (Fly Redis or external)
- Telegram bot token from BotFather
- All required env vars ready (see `docs/ops/secrets_env_guide.md`)

---

## 1. Clone and Configure

```bash
git clone https://github.com/bayuewalker/walkermind-os
cd walkermind-os/projects/polymarket/polyquantbot
```

Review `fly.toml` — confirm app name and region match your target environment.

---

## 2. Set Environment Secrets

Set all required secrets via Fly CLI before first deploy:

```bash
fly secrets set \
  DB_DSN="postgresql://user:pass@host:5432/crusaderbot" \
  CRUSADER_DB_RUNTIME_ENABLED="true" \
  REDIS_URL="redis://host:6379" \
  TELEGRAM_BOT_TOKEN="<your-bot-token>" \
  TELEGRAM_CHAT_ID="<your-operator-chat-id>" \
  CRUSADER_OPERATOR_API_KEY="<random-32-char-key>" \
  ORCHESTRATION_ADMIN_TOKEN="<random-32-char-key>" \
  SETTLEMENT_ADMIN_TOKEN="<random-32-char-key>" \
  -a crusaderbot
```

For optional secrets (Falcon signals, Sentry), see `docs/ops/secrets_env_guide.md`.

**Do NOT set activation guards yet** (`EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, `ENABLE_LIVE_TRADING`). Paper mode is default and safe.

---

## 3. Apply Database Migrations

Run migrations against the target database before deploying the app:

```bash
# Migration 1: Settlement domain tables
psql $DB_DSN -f infra/db/migrations/001_settlement_tables.sql

# Migration 2: Capital mode confirmations table
psql $DB_DSN -f infra/db/migrations/002_capital_mode_confirmations.sql
```

If using Fly Postgres, connect first:

```bash
fly proxy 5432 -a <your-postgres-app-name>
# Then in a separate terminal:
psql postgresql://user:pass@localhost:5432/crusaderbot -f infra/db/migrations/001_settlement_tables.sql
psql postgresql://user:pass@localhost:5432/crusaderbot -f infra/db/migrations/002_capital_mode_confirmations.sql
```

The runtime also auto-creates tables via `_apply_schema()` on startup. Explicit migrations are recommended for schema accuracy.

---

## 4. Deploy

```bash
fly deploy -a crusaderbot
```

The `Dockerfile` starts a single `app` process. `fly.toml` is configured for a single-machine runtime with embedded Telegram polling — there are no separate worker or bot processes in Fly. The API, Telegram bot, and worker all run within the same machine under the `app` process.

---

## 5. Verify Health

```bash
fly status -a crusaderbot
fly logs -a crusaderbot

# Health check
curl https://crusaderbot.fly.dev/health
curl https://crusaderbot.fly.dev/ready
curl https://crusaderbot.fly.dev/beta/status
```

Expected:
- `/health` → `{"status": "ok"}`
- `/ready` → `{"status": "ready", "readiness": {...}}` (HTTP 503 + `"status": "not_ready"` if env/DB/Telegram missing)
- `/beta/status` → `{"mode": "PAPER", "autotrade": false, "kill_switch": false, "paper_only_execution_boundary": true, ...}`

---

## 6. Verify Telegram Bot

Send `/start` to the bot in Telegram. The bot should reply with a welcome message.
Send `/status` to confirm paper mode is active.

---

## 7. Redis Setup

If using Fly Redis:

```bash
fly redis create
# Note the Redis URL from the output and set it as REDIS_URL secret
fly secrets set REDIS_URL="redis://..." -a crusaderbot
```

If using external Redis, ensure the Redis URL is reachable from the Fly network.

---

## 8. Rollback

To roll back to a previous release:

```bash
fly releases list -a crusaderbot
fly deploy --image <previous-image-ref> -a crusaderbot --strategy immediate
```

Do NOT use `git revert` on a deployed Fly app — always use image-based rollback.

---

## 9. Activation (Capital Mode — when authorized)

Capital mode activation is a separate operator step requiring explicit WARP🔹CMD + Mr. Walker approval. Do NOT perform these steps without explicit authorization.

When authorized:
1. Set env guards: see `docs/ops/secrets_env_guide.md` §Activation Sequence
2. Issue `/capital_mode_confirm` two-step on Telegram (see `docs/operator_runbook.md` §9)

---

## Troubleshooting

- Deploy fails at health check → check `fly logs`, verify `DB_DSN` and `REDIS_URL` are set
- Bot not responding → check `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
- `/ready` returns missing env → check `fly secrets list`
- DB connection error → verify migration was applied and DB_DSN points to correct host

For runtime troubleshooting, see `docs/fly_runtime_troubleshooting.md`.
