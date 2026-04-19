# Phase 8.3 — Public Paper Beta Spine Runtime Contract

## Entrypoints
- API: `projects/polymarket/polyquantbot/server/main.py`
- Telegram Bot: `projects/polymarket/polyquantbot/client/telegram/bot.py`
- Worker: `projects/polymarket/polyquantbot/scripts/run_worker.py`
- Launch helpers:
  - `projects/polymarket/polyquantbot/scripts/run_api.py`
  - `projects/polymarket/polyquantbot/scripts/run_bot.py`

## FastAPI control plane
- `GET /health`
- `GET /ready`
- `GET /beta/status`
- `POST /beta/mode`
- `POST /beta/autotrade`
- `POST /beta/kill`
- `GET /beta/positions`
- `GET /beta/markets`
- `GET /beta/market360/{condition_id}`
- `GET /beta/social?topic=...`

## Falcon backend-managed contract
Falcon config is backend-managed only using environment variables:
- `FALCON_API_KEY`
- `FALCON_BASE_URL`
- `FALCON_TIMEOUT`
- `FALCON_ENABLED`

No user-managed key flow and no `/setkey` command is provided.

## Telegram command shell (public beta)
- `/start`
- `/connect_wallet`
- `/mode [paper|live]`
- `/autotrade [on|off]`
- `/positions`
- `/pnl`
- `/risk`
- `/status`
- `/markets [query]`
- `/market360 [condition_id]`
- `/social [topic]`
- `/kill`

Manual trade-entry commands are intentionally excluded.

## Paper worker flow
`market_sync -> signal_runner -> risk_monitor -> position_monitor -> price_updater`

Execution mode defaults to `paper`. Risk gate enforces:
- positive EV
- minimum edge threshold
- liquidity floor
- drawdown stop
- exposure cap
- idempotency
- kill switch

Write-side execution for this beta slice remains paper-only and never sends live orders.
