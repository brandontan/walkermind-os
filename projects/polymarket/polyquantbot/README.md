# CrusaderBot

Non-custodial Polymarket trading platform — closed beta, paper-only mode.

---

## What is this?

CrusaderBot is an algorithmic trading system for the Polymarket prediction market. It operates in **paper-only** mode by default. No real capital is deployed without explicit operator activation of all three environment guards.

**Current status:** Priority 8 capital readiness build complete. Paper-only boundary preserved. Awaiting operator env-gate + activation ceremony before any real-capital path becomes active.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| API runtime | FastAPI |
| Bot runtime | Telegram Bot (python-telegram-bot) |
| Database | PostgreSQL (asyncpg) |
| Cache | Redis |
| Market data | Polymarket CLOB API |
| Real-time | WebSocket + Polygon |
| Deployment | Fly.io |

---

## Current Capabilities

- Paper trading worker spine (`market_sync`, `signal_runner`, `risk_monitor`, `position_monitor`)
- Multi-user backend: user, account, wallet ownership boundaries
- Capital readiness foundation: `CapitalModeConfig`, `CapitalRiskGate`, `LiveExecutionGuard`
- Two-layer capital mode confirmation gate (`CAPITAL_MODE_CONFIRMED` env + DB receipt via `/capital_mode_confirm`)
- Real CLOB execution path: `ClobExecutionAdapter` + `LiveMarketDataProvider` (NARROW INTEGRATION — guarded, not active)
- Settlement engine with retry, reconciliation, operator controls
- Multi-wallet orchestration with `WalletOrchestrator` + overlay controls
- Portfolio management: positions, PnL, exposure, guardrails
- Telegram operator shell: `/status`, `/paper`, `/positions`, `/pnl`, `/kill`, `/capital_mode_confirm`, and more
- FastAPI control plane: `/health`, `/ready`, `/beta/status`, `/beta/admin`
- Structured logging via `structlog`
- Fly.io deploy-ready (`fly.toml`, `Dockerfile`)

---

## What is NOT active

- `EXECUTION_PATH_VALIDATED` — NOT SET
- `CAPITAL_MODE_CONFIRMED` — NOT SET
- `ENABLE_LIVE_TRADING` — NOT SET

No live-trading authority or production-capital readiness is claimed until all three guards are explicitly activated by the operator.

---

## Safety Boundaries (fixed — never override)

| Rule | Value |
|---|---|
| Kelly fraction | 0.25 (fractional only) |
| Max position size | <= 10% of total capital |
| Daily loss limit | -$2,000 hard stop |
| Max drawdown | > 8% — system halt |
| Min orderbook depth | $10,000 |
| Kill switch | Telegram-accessible, immediate halt |

---

## Project Structure

```
projects/polymarket/polyquantbot/
├── client/telegram/          — Telegram bot runtime
├── client/web/               — Web client surfaces
├── server/                   — FastAPI backend
│   ├── api/                  — Route handlers
│   ├── services/             — Business logic
│   └── storage/              — Persistence boundaries
├── core/                     — Capital mode config, guards, execution memory
├── risk/                     — CapitalRiskGate, WalletFinancialProvider
├── execution/                — ClobExecutionAdapter, LiveExecutionGuard
├── monitoring/               — Circuit breaker, observability
├── workers/                  — PaperBetaWorker, settlement worker
├── infra/db/                 — DB startup, migrations
├── scripts/                  — run_api.py, run_bot.py, run_worker.py
├── configs/                  — Runtime config models
├── docs/                     — Operator docs, guides, runbooks
└── state/                    — PROJECT_STATE.md, ROADMAP.md, WORKTODO.md
```

---

## Key Reference Files

| File | Purpose |
|---|---|
| `state/ROADMAP.md` | Milestone and phase planning truth |
| `state/WORKTODO.md` | Granular task tracking |
| `state/PROJECT_STATE.md` | Current operational truth |
| `docs/ops/deployment_guide.md` | Fly.io deploy steps + DB migration |
| `docs/ops/secrets_env_guide.md` | Env var reference + activation sequence |
| `docs/ops/runbook_quick_ref.md` | Operator commands + emergency procedures |
| `docs/onboarding.md` | How to run locally |
| `docs/operator_runbook.md` | Full operator runbook (§1–§9) |

---

## Quick Start

See `docs/onboarding.md` for local setup and `docs/ops/deployment_guide.md` for Fly.io deployment.
