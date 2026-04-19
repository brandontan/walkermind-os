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
- `GET /beta/pnl`
- `GET /beta/risk`
- `GET /beta/markets`
- `GET /beta/market360/{condition_id}`
- `GET /beta/social?topic=...`

### Readiness truth (Phase 8.4 hardening)
`GET /ready` reports readiness dimensions for this lane:
- API boot completion (`api_boot_complete`)
- Worker runtime status (`startup_complete`, `active`, `shutdown_complete`, `iterations_total`, `last_error`)
- Worker prerequisites (`paper_mode_enforced`, `autotrade_enabled`, `kill_switch_enabled`)
- Falcon config truth (`enabled`, `api_key_configured`, `candidate_source_contract`)
- Control-plane execution boundary (`paper_only_execution_boundary=true`)

Readiness intentionally does **not** overclaim external dependency health that is not actively probed.

## Falcon backend-managed contract
Falcon config is backend-managed only using environment variables:
- `FALCON_API_KEY` (required only when `FALCON_ENABLED=true`)
- `FALCON_BASE_URL`
- `FALCON_TIMEOUT`
- `FALCON_ENABLED`

No user-managed key flow and no `/setkey` command is provided.

### Runtime truth note
This lane is **NARROW INTEGRATION**. Falcon market/candidate/social data currently includes bounded placeholder/sample behavior in `FalconGateway` and is not yet a full production retrieval surface.

## Telegram command shell (public beta)
- `/start`
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
`/mode live` is accepted as control-plane state only in this phase; execution remains paper-only.

## Paper worker flow
`market_sync -> signal_runner -> risk_monitor -> position_monitor -> price_updater`

Execution mode defaults to `paper`. New entries are blocked when:
- `autotrade_enabled=false`
- `kill_switch=true`
- `mode != paper` (`mode_live_paper_execution_disabled`)
- risk gate rejects EV/edge/liquidity/drawdown/exposure/idempotency checks

Monitoring/update stages still run even when entry creation is blocked.
Worker iteration logs include candidate count, accepted/rejected counts, skip reasons, rejection reason counts, and current position count.

## Fly deploy truth
Fly runtime is paper-mode by default. To activate Falcon-backed candidate generation, deploy must provide secret-backed Falcon configuration (`FALCON_ENABLED=true` + `FALCON_API_KEY` and optional base URL override).


## Operator expectations (public paper beta)
- Telegram is a **control shell**, not a manual trade terminal.
- `/mode live` updates control-plane state only; execution stays paper-only in this phase.
- `/autotrade on` is rejected when mode is `live` to preserve paper-only boundary truth.
- `/kill` always forces autotrade OFF and sets a hard paper-beta execution block.
- Unknown Telegram commands should fall back to a concise supported-command hint.

## Known limitations
- Falcon data surfaces remain narrow/placeholder-bounded outside `market_360`; signal quality is not a production claim.
- This lane does not include live execution authority, user-managed Falcon keys, dashboard expansion, or manual trade-entry commands.
