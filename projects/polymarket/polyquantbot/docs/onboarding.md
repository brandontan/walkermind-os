# CrusaderBot — Onboarding Guide

How to run CrusaderBot locally for development and paper trading.

---

## Prerequisites

- Python 3.11+
- PostgreSQL (local or remote)
- Redis (local or remote)
- Telegram bot token (via BotFather)
- `.env` file with required vars (see below)

---

## Setup

```bash
git clone https://github.com/bayuewalker/walkermind-os
cd walkermind-os/projects/polymarket/polyquantbot

python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Minimum Required Environment Variables

Copy `.env.example` (if present) or create `.env` manually:

```
# Database
DB_DSN=postgresql://user:pass@localhost:5432/crusaderbot
CRUSADER_DB_RUNTIME_ENABLED=true

# Redis
REDIS_URL=redis://localhost:6379

# Telegram
TELEGRAM_BOT_TOKEN=<your-bot-token>
TELEGRAM_CHAT_ID=<your-operator-chat-id>

# Falcon (optional — signals disabled if not set)
FALCON_ENABLED=false
FALCON_API_KEY=
FALCON_BASE_URL=
FALCON_TIMEOUT=30

# Operator / Admin (admin routes)
CRUSADER_OPERATOR_API_KEY=<generate-a-random-key>
ORCHESTRATION_ADMIN_TOKEN=<generate-a-random-key>
SETTLEMENT_ADMIN_TOKEN=<generate-a-random-key>
```

For the full env var reference, see `docs/ops/secrets_env_guide.md`.

**Paper trading only:** Do NOT set `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, or `ENABLE_LIVE_TRADING` for local paper testing.

---

## Apply Database Migrations

Run the SQL migrations before starting the API:

```bash
psql $DATABASE_URL -f infra/db/migrations/001_settlement_tables.sql
psql $DATABASE_URL -f infra/db/migrations/002_capital_mode_confirmations.sql
```

The API runtime also auto-creates tables on startup via `_apply_schema()` — but explicit migration runs are recommended for production.

---

## Running the Services

Three independent entrypoints — run each in a separate terminal:

```bash
# FastAPI control plane
python scripts/run_api.py

# Telegram bot
python scripts/run_bot.py

# Paper trading worker
python scripts/run_worker.py
```

The API starts on `PORT` (default 8080). Health check: `GET /health`.

---

## Verifying Paper Trading Mode

Once the API is running:

```bash
curl http://localhost:8080/ready
curl http://localhost:8080/beta/status
```

The `/beta/status` response will show `paper_mode: true` and `execution_path_validated: false` confirming paper-only operation.

On Telegram, send `/status` to the bot to confirm paper mode is active.

---

## Running Tests

```bash
pytest tests/ -q
```

All 167+ tests should pass. Paper-trading mode guards are verified by the test suite.

---

## Key Concepts

**Paper mode** — all execution calls are intercepted by `PaperBetaWorker` and no real orders are placed. The `ENABLE_LIVE_TRADING` guard is a hard code-level block that prevents any live execution path from running unless the env var is set.

**Operator commands** — the Telegram bot exposes operator commands prefixed with `/`. Full list in `docs/ops/runbook_quick_ref.md`.

**Kill switch** — send `/kill` on Telegram to immediately halt all worker activity. Re-enable via `/resume`.

---

## Known Issues

See `docs/support.md` for current known issues and deferred items.
