# CrusaderBot Runtime Surface Mapping

## What stayed
- `projects/polymarket/polyquantbot/main.py` remains in place as the legacy monolithic runtime entrypoint for compatibility during this phase.
- Existing domain packages such as `core/`, `execution/`, `risk/`, `monitoring/`, and `telegram/` remain importable and unchanged by this runtime split.

## What was introduced
- `projects/polymarket/polyquantbot/server/main.py` is now the dedicated FastAPI control-plane surface for Fly.io.
- `projects/polymarket/polyquantbot/client/telegram/bot.py` is now the dedicated Telegram bootstrap surface.
- `projects/polymarket/polyquantbot/scripts/run_api.py` is the deploy-facing API entrypoint.
- `projects/polymarket/polyquantbot/scripts/run_bot.py` is the Telegram runtime entrypoint.
- `projects/polymarket/polyquantbot/scripts/run_worker.py` is the worker bootstrap placeholder for multi-surface deployment growth.

## Current-to-target mapping
- `api/` -> legacy API and webhook surfaces pending gradual normalization into `server/api/`.
- `telegram/` -> legacy Telegram handlers pending gradual normalization into `client/telegram/`.
- `frontend/`, `ui/`, and `views/` -> future web-facing consolidation target under `client/web/`.
- `config/` -> future normalization target under `configs/`.
- `utils/` -> future normalization target under `server/utils/`.
- `wallet/` and current portfolio-related logic -> future normalization target under `server/portfolio/`.
- `infra/`, `platform/`, and mixed adapters -> future normalization target under `server/integrations/`, `server/storage/`, and `server/services/`.
- `legacy/` remains the explicit boundary for retired or quarantined flows, but this phase does not relocate active runtime code into it.

## What is now legacy
- Fly.io should no longer use `projects/polymarket/polyquantbot/main.py` as the default runtime command.
- The current root `main.py` is still oversized and remains the orchestration sink until a later extraction pass.
- Existing Telegram and API implementation layers remain mixed and are not yet fully normalized into the Crusader multi-user blueprint.

## Fly.io runtime contract
- Fly now targets the FastAPI surface through `projects/polymarket/polyquantbot/scripts/run_api.py`.
- Health checks target `GET /health`.
- Readiness checks target `GET /ready`.
- The API binds Fly-injected `PORT`.
