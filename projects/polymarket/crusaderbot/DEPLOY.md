# CrusaderBot — Fly.io Deployment Guide

## Prerequisites

```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh
fly auth login
```

---

## Step 1 — Launch the app (first time only)

Run this from inside the `crusaderbot/` directory. **All `fly` commands below
should be run from `crusaderbot/`** — that directory contains `fly.toml` and
is the Docker build context (the Dockerfile copies its contents into the right
package layout inside the image).

```bash
cd crusaderbot
fly launch \
  --name crusaderbot \
  --region sin \
  --no-deploy \
  --copy-config
```

> `sin` = Singapore, the closest Fly.io region to Asia/Jakarta.
> `--no-deploy` lets you set secrets before the first boot.
> Accept "yes" when asked whether to copy the existing `fly.toml`.

---

## Step 2 — Provision Postgres

```bash
fly postgres create \
  --name crusaderbot-db \
  --region sin \
  --initial-cluster-size 1 \
  --vm-size shared-cpu-1x \
  --volume-size 10

fly postgres attach crusaderbot-db --app crusaderbot
```

This automatically injects `DATABASE_URL` as a Fly secret.

---

## Step 3 — Provision Redis (recommended for multi-instance)

```bash
fly redis create \
  --name crusaderbot-redis \
  --region sin \
  --no-replicas

# Copy the upstash redis URL from the output above, then:
fly secrets set REDIS_URL="rediss://..." --app crusaderbot
```

---

## Step 4 — Mirror secrets from Replit

Set every secret that lives in your Replit environment:

```bash
fly secrets set \
  TELEGRAM_BOT_TOKEN="..."         \
  OPERATOR_CHAT_ID="..."           \
  POLYGON_RPC_URL="..."            \
  WALLET_HD_SEED="..."             \
  WALLET_ENCRYPTION_KEY="..."      \
  ADMIN_API_TOKEN="..."            \
  POLYMARKET_API_KEY="..."         \
  POLYMARKET_API_SECRET="..."      \
  POLYMARKET_PASSPHRASE="..."      \
  MASTER_WALLET_ADDRESS="..."      \
  MASTER_WALLET_PRIVATE_KEY="..."  \
  --app crusaderbot
```

Leave out secrets that don't apply yet (e.g., Polymarket keys if not going live).

---

## Step 5 — First deploy (polling mode)

Deploy without a webhook URL first to verify the app boots correctly:

```bash
fly deploy --app crusaderbot
fly logs   --app crusaderbot   # confirm "CrusaderBot up"
```

---

## Step 6 — Switch to webhook mode

Set **both** the webhook URL and a random secret together. Both must be
present before the webhook endpoint becomes active — the endpoint returns 404
in polling mode and always enforces the secret in webhook mode.

```bash
WEBHOOK_SECRET=$(openssl rand -hex 32)

fly secrets set \
  TELEGRAM_WEBHOOK_URL="https://crusaderbot.fly.dev/telegram/webhook" \
  TELEGRAM_WEBHOOK_SECRET="${WEBHOOK_SECRET}" \
  --app crusaderbot

fly deploy --app crusaderbot   # picks up new secrets
```

On the next boot, the app will call `setWebhook` automatically and log:

```
Telegram webhook registered: https://crusaderbot.fly.dev/telegram/webhook
```

> **Important:** Never set `TELEGRAM_WEBHOOK_URL` without also setting
> `TELEGRAM_WEBHOOK_SECRET`. If `TELEGRAM_WEBHOOK_SECRET` is missing the app
> will generate an ephemeral secret at startup and log a warning (the secret
> value itself is never logged). Because the ephemeral secret changes on every
> restart, Telegram's webhook calls will be rejected after the next deploy.
> Always set both variables together.

---

## Step 7 — Smoke test

Open a personal Telegram chat with the bot and send:

```
/start
/wallet
/setup
```

Confirm you receive responses. Check scheduler timezone:

```bash
fly ssh console --app crusaderbot
python3 -c "from crusaderbot.scheduler import setup_scheduler; s = setup_scheduler(); [print(j.id, j.next_run_time) for j in s.get_jobs()]"
```

All `next_run_time` values should show UTC+7 (Asia/Jakarta) offset.

---

## Step 8 — Activation guard sequence (live trading)

All four conditions must be true before any live order can be submitted:

1. Run paper-only for 7+ days; confirm zero silent failures.
2. `fly secrets set EXECUTION_PATH_VALIDATED=true --app crusaderbot`
3. `fly secrets set CAPITAL_MODE_CONFIRMED=true   --app crusaderbot`
4. Operator promotes user(s) via `/allowlist <id> 4` in the bot.
5. User toggles **Setup → Mode → Live** in Telegram.

---

## Useful Fly.io commands

```bash
fly status   --app crusaderbot          # instance health
fly logs     --app crusaderbot          # tail live logs
fly ssh console --app crusaderbot       # shell into running instance
fly secrets list --app crusaderbot      # verify all secrets are set
fly postgres connect --app crusaderbot-db  # psql into the DB
fly scale count 1 --app crusaderbot     # ensure single instance (avoid duplicate polling)
```

---

## Process model notes

- Single-process (API + scheduler + bot) keeps the setup simple for low traffic.
- To split API vs worker later, add a `[processes]` section to `fly.toml` and a `Procfile`.
- Keep `fly scale count 1` unless you have Redis and have verified the scheduler de-duplication logic.
