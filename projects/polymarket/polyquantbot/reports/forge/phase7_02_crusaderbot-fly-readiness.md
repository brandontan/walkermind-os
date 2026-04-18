# What was built

CrusaderBot now has explicit runtime surfaces inside `projects/polymarket/polyquantbot/` for:
- FastAPI control plane at `server/main.py`
- Telegram bootstrap at `client/telegram/bot.py`
- deploy/run scripts at `scripts/run_api.py`, `scripts/run_bot.py`, and `scripts/run_worker.py`

Fly.io and Docker now target the FastAPI runtime surface instead of the monolithic root `main.py`. The new API surface exposes `/health` and `/ready`, binds Fly-injected `PORT`, performs deterministic startup validation, and logs graceful shutdown lifecycle events. The runtime-facing service name is `CrusaderBot`.

# Current system architecture

Current scoped runtime split after this task:
- Fly.io / Docker -> `projects/polymarket/polyquantbot/scripts/run_api.py`
- `scripts/run_api.py` -> `projects/polymarket/polyquantbot/server/main.py`
- `server/main.py` -> FastAPI control plane (`/health`, `/ready`, root docs landing)
- Telegram runtime bootstrap -> `projects/polymarket/polyquantbot/scripts/run_bot.py` -> `projects/polymarket/polyquantbot/client/telegram/bot.py`
- Worker placeholder -> `projects/polymarket/polyquantbot/scripts/run_worker.py`
- Legacy monolithic runtime remains at `projects/polymarket/polyquantbot/main.py` and is explicitly documented as a compatibility-era legacy boundary, not the Fly default entrypoint

# Files created / modified

Created:
- `projects/polymarket/polyquantbot/client/__init__.py`
- `projects/polymarket/polyquantbot/client/telegram/__init__.py`
- `projects/polymarket/polyquantbot/client/telegram/bot.py`
- `projects/polymarket/polyquantbot/server/__init__.py`
- `projects/polymarket/polyquantbot/server/api/__init__.py`
- `projects/polymarket/polyquantbot/server/api/routes.py`
- `projects/polymarket/polyquantbot/server/core/__init__.py`
- `projects/polymarket/polyquantbot/server/core/runtime.py`
- `projects/polymarket/polyquantbot/server/main.py`
- `projects/polymarket/polyquantbot/scripts/run_api.py`
- `projects/polymarket/polyquantbot/scripts/run_bot.py`
- `projects/polymarket/polyquantbot/scripts/run_worker.py`
- `projects/polymarket/polyquantbot/docs/crusader_runtime_surface.md`
- `projects/polymarket/polyquantbot/tests/test_crusader_runtime_surface.py`

Modified:
- `projects/polymarket/polyquantbot/requirements.txt`
- `projects/polymarket/polyquantbot/Dockerfile`
- `projects/polymarket/polyquantbot/fly.toml`

# What is working

- Runtime-facing branding on the new API and bootstrap surfaces uses `CrusaderBot`
- FastAPI control-plane surface exists and is launchable via `projects/polymarket/polyquantbot/scripts/run_api.py`
- `/health` and `/ready` are implemented on the new API surface
- API startup validates `PORT`, `TRADING_MODE`, `CRUSADER_STARTUP_MODE`, and the live-trading guard contract
- Docker healthcheck and Fly health check both target `/health`
- Docker default command no longer points at the monolithic root `main.py`
- Telegram runtime can now be launched independently from the API runtime surface
- The current-to-target mapping and explicit legacy boundary are documented

# Known issues

- Root `projects/polymarket/polyquantbot/main.py` remains oversized and is not yet reduced to a thin compatibility shim in this pass
- Existing `api/`, `telegram/`, `frontend/`, `ui/`, and `views/` layers remain mixed and are only partially normalized by the new runtime split
- This pass introduces deploy-ready runtime surfaces, but does not relocate legacy handlers or old orchestration code into `legacy/`

# What is next

- Run SENTINEL validation on the new Fly.io deploy path, FastAPI lifecycle contract, and startup validation behavior
- Decide the next extraction pass for reducing root `main.py` into a true compatibility shim
- Continue gradual normalization of legacy API and Telegram layers into the Crusader multi-user blueprint

Validation Tier   : MAJOR
Claim Level       : FULL RUNTIME INTEGRATION
Validation Target : CrusaderBot Fly.io API control-plane runtime, deploy entrypoints, Docker/Fly runtime contract, and startup/health lifecycle surfaces inside `projects/polymarket/polyquantbot/`
Not in Scope      : legacy root `main.py` extraction, multi-user storage rollout, Telegram handler migration, worker orchestration, database/websocket runtime relocation, and broad folder renames
Suggested Next    : SENTINEL review required before merge
