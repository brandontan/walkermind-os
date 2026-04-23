# Walker AI DevTrade Team

## Overview
A multi-agent AI-driven trading ecosystem for managing and executing trading strategies across Polymarket, Kalshi, TradingView, and MetaTrader 4/5.

## Architecture
- **Frontend**: React + Vite (walker_devops) — runs on port 5000
- **Backend API**: Express (walker_devops/server) — runs on port 8787
- **Trading Bot**: Python/FastAPI (polyquantbot) — PolyQuantBot core trading engine
- **Agents**: Multi-agent system (COMMANDER, FORGE-X, SENTINEL, BRIEFER)

## Project Structure
```
projects/
  app/walker_devops/     # DevOps launch planner (React frontend + Express backend)
    frontend/            # React + Vite app
    server/              # Express API
  polymarket/
    polyquantbot/        # Python trading bot (FastAPI, asyncio)
  mt5/                   # MetaTrader 5 Expert Advisors
  tradingview/           # TradingView Pine Scripts
lib/                     # Shared Python libraries
docs/                    # System blueprints and knowledge base
```

## Running the Application
The workflow "Start application" runs the walker_devops app:
- Command: `cd projects/app/walker_devops && npm run dev`
- Frontend: http://localhost:5000 (Vite)
- Backend API: http://localhost:8787 (Express)

## Dependencies
- **Python**: pip + requirements.txt (aiohttp, asyncpg, redis, structlog, python-telegram-bot, etc.)
- **Node.js**: npm + projects/app/walker_devops/package.json (React, Vite, Express, @openai/agents)

## Environment Variables
- `OPENAI_AGENTS_DISABLE_TRACING=1` — Disable OpenAI Agents tracing
- `TRADING_MODE` — "PAPER" | "LIVE" (default: "PAPER")
- `ENABLE_LIVE_TRADING` — "true" required for LIVE mode
- `DASHBOARD_ENABLED` — "true" to start dashboard server
- `DASHBOARD_API_KEY` — Bearer token for dashboard auth
- `REDIS_URL` — Redis connection URL
- `DB_DSN` — PostgreSQL DSN
- `TELEGRAM_BOT_TOKEN` — Telegram bot token
- `TELEGRAM_CHAT_ID` — Telegram chat ID
