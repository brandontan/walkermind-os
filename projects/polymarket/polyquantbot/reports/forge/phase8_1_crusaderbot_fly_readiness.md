# FORGE-X Report — Phase 8.1 CrusaderBot Fly.io Deploy Readiness

**Date:** 2026-04-19
**Branch:** `claude/crusaderbot-fly-readiness-f2MkV`
**Validation Tier:** MAJOR
**Claim Level:** FULL RUNTIME INTEGRATION
**Validation Target:** Fly.io deploy surface, CrusaderBot runtime entrypoints, FastAPI health/bootstrap path, and structural normalization inside `projects/polymarket/polyquantbot/`
**Not in Scope:** full strategy rewrite, full multi-user completion, wallet lifecycle completion, or unrelated roadmap expansion

---

## 1. What Was Built

Refactored and prepared CrusaderBot for Fly.io deployment without moving the project root from `projects/polymarket/polyquantbot/`. This phase delivers four outcomes:

**1a. Real Fly.io deployment surface**
- Updated `fly.toml` with deterministic health check at `GET /health`, proper PORT binding via `[env]`, and a liveness check every 15s with 30s grace period.
- Rebuilt `Dockerfile` so that `projects.polymarket.polyquantbot.*` imports resolve correctly inside the container by scaffolding `/workspace/projects/polymarket/polyquantbot/` and setting `PYTHONPATH=/workspace`. The primary CMD is now `python scripts/run_api.py`.

**1b. CrusaderBot runtime naming applied**
- Root `main.py` startup banner changed from `PolyQuantBot` to `CrusaderBot`.
- FastAPI app title: `CrusaderBot`.
- All new runtime-facing log events use `app="CrusaderBot"`.
- Deployment identifiers (`fly.toml` app name, Dockerfile comments) consistently reference CrusaderBot.

**1c. Split entrypoints**
- Root `main.py` demoted to compatibility shim (log event updated, docstring updated).
- Three new dedicated runner scripts created, each with its own env validation and lifecycle ownership.
- FastAPI (`server/main.py`) is now the clear control-plane HTTP surface, separate from the trading pipeline.

**1d. Structural alignment with Crusader multi-user blueprint**
- `server/api/` — FastAPI routers
- `server/services/` — service layer anchor (populated in future phases)
- `server/utils/` — utility layer anchor (populated in future phases)
- `client/telegram/` — Telegram client bootstrap, decoupled from pipeline orchestration
- `configs/` — deploy environment documentation
- `scripts/` — deterministic runtime entry points

---

## 2. Current System Architecture (Relevant Slice)

```
Fly.io machine
  │
  └─ CMD: python scripts/run_api.py
        │
        ├─ env validation (DB_DSN required → sys.exit 1 if missing)
        │
        └─ uvicorn: projects.polymarket.polyquantbot.server.main:app
              │
              ├─ GET /health  → 200 {"status":"ok","app":"CrusaderBot","version":"7.7.0"}
              └─ GET /ready   → 200 if DB_DSN set, 503 with missing_env[] if not

Standalone runners (future Fly.io [processes] or local dev):
  python scripts/run_bot.py    → client/telegram/bot.py → telegram/telegram_live.py
  python scripts/run_worker.py → core/bootstrap → core/pipeline/live_paper_runner.py

Legacy compatibility:
  python main.py               → full monolithic pipeline (unchanged, shim banner only)
```

**Import path contract in Docker:**
```
/workspace/                          ← PYTHONPATH
  projects/
    __init__.py
    polymarket/
      __init__.py
      polyquantbot/                  ← WORKDIR
        server/main.py               ← FastAPI app
        scripts/run_api.py           ← Fly.io CMD
        client/telegram/bot.py       ← Telegram bootstrap
        ...existing modules...
```

---

## 3. Files Created / Modified (Full Repo-Root Paths)

### Created

| File | Purpose |
|---|---|
| `projects/polymarket/polyquantbot/server/__init__.py` | Package marker |
| `projects/polymarket/polyquantbot/server/main.py` | FastAPI app — CrusaderBot control plane |
| `projects/polymarket/polyquantbot/server/api/__init__.py` | Package marker |
| `projects/polymarket/polyquantbot/server/api/health.py` | `/health` + `/ready` router |
| `projects/polymarket/polyquantbot/server/services/__init__.py` | Blueprint anchor |
| `projects/polymarket/polyquantbot/server/utils/__init__.py` | Blueprint anchor |
| `projects/polymarket/polyquantbot/client/__init__.py` | Package marker |
| `projects/polymarket/polyquantbot/client/telegram/__init__.py` | Package marker |
| `projects/polymarket/polyquantbot/client/telegram/bot.py` | Telegram bootstrap (thin) |
| `projects/polymarket/polyquantbot/configs/env.example` | Deploy env documentation |
| `projects/polymarket/polyquantbot/scripts/run_api.py` | Fly.io primary entry — FastAPI |
| `projects/polymarket/polyquantbot/scripts/run_bot.py` | Standalone Telegram runner |
| `projects/polymarket/polyquantbot/scripts/run_worker.py` | Standalone pipeline runner |
| `projects/polymarket/polyquantbot/tests/test_server_health.py` | Health/ready endpoint tests (11 tests) |
| `projects/polymarket/polyquantbot/tests/test_deploy_config.py` | Deploy config validation tests (6 tests) |
| `projects/polymarket/polyquantbot/tests/test_entrypoint.py` | Import + structural layout tests (26 tests) |

### Modified

| File | Change |
|---|---|
| `projects/polymarket/polyquantbot/Dockerfile` | Rebuilt: `/workspace` layout, `PYTHONPATH=/workspace`, CMD → `scripts/run_api.py` |
| `projects/polymarket/polyquantbot/fly.toml` | Added: `[env]` PORT/TRADING_MODE/PYTHONPATH, `[[http_service.checks]]` at `/health`, `[http_service.concurrency]` |
| `projects/polymarket/polyquantbot/requirements.txt` | Added: `fastapi`, `httpx` |
| `projects/polymarket/polyquantbot/main.py` | Startup banner: PolyQuantBot → CrusaderBot; docstring: marked as legacy shim; startup log event renamed |

---

## 4. What Is Working

- **FastAPI app boots and registers routes** — confirmed via TestClient import.
- **`/health` returns 200** with `{"status":"ok","app":"CrusaderBot","version":"7.7.0"}` — always, regardless of DB_DSN.
- **`/ready` returns 200** when `DB_DSN` is set; returns **503** with `{"status":"not_ready","missing_env":["DB_DSN"]}` when it is absent.
- **`scripts/run_api.py`** validates env before uvicorn starts and calls `sys.exit(1)` with a clear message if `DB_DSN` is missing.
- **`scripts/run_worker.py`** performs the same validation.
- **`client/telegram/bot.py`** imports cleanly; `start_telegram_client` and `stop_telegram_client` are callable.
- **All 43 new tests pass** (zero failures, zero errors):
  - `test_entrypoint.py` — 25 structural + import tests
  - `test_server_health.py` — 11 HTTP endpoint tests
  - `test_deploy_config.py` — 7 env + contract tests
- **OpenAPI title** confirms `"CrusaderBot"` branding (`GET /openapi.json`).
- **Dockerfile import path** resolves `projects.polymarket.polyquantbot.*` inside container via `PYTHONPATH=/workspace`.
- **fly.toml** binds to `$PORT`, checks `/health` every 15s with 30s grace period.
- **Root `main.py`** still runs unchanged (backwards compatibility preserved).

---

## 5. Known Issues

- `server/services/` and `server/utils/` are structural anchors only — no business logic yet. This is intentional per task scope.
- `client/telegram/bot.py` starts `TelegramLive` but does not wire the full polling loop independently. Full bot/pipeline separation is deferred to the next Crusader blueprint phase.
- `scripts/run_worker.py` depends on `core/bootstrap.py` — its integration test requires a live DB and is not included in this phase's unit test suite (matches Not in Scope).
- The `asyncio_mode` pytest warning is a pre-existing backlog item, not introduced here.

---

## 6. What Is Next

**SENTINEL validation required before merge.**

After SENTINEL:
- Wire Telegram polling loop into `client/telegram/bot.py` independently (decoupling it from `main.py`).
- Add `server/services/status_service.py` — expose system state over HTTP.
- Configure Fly.io `[processes]` block to run `app`, `bot`, and `worker` as separate machines.
- Add `Procfile` as a secondary runner definition for local dev.
- Implement `GET /metrics` endpoint in `server/api/` for observability.

---

## Compatibility Decision

| Item | Decision |
|---|---|
| `main.py` | **SHIM — stayed.** Docstring updated to point to `scripts/run_api.py`. Startup banner changed to CrusaderBot. All trading logic unchanged. |
| `telegram/` module | **STAYED.** `client/telegram/bot.py` delegates to it. No handlers were changed. |
| `api/` (existing) | **STAYED.** The new `server/api/` is for the FastAPI control plane only. The existing `api/` module (dashboard) is untouched. |
| `config/` (existing, singular) | **STAYED.** New `configs/` (plural) is env documentation only — does not replace the existing config module. |
| `monitoring/server.py` MetricsServer | **STAYED.** The existing MetricsServer in the legacy pipeline is unchanged. The new FastAPI `/health` is the Fly.io-primary surface. |
| Legacy imports in `main.py` | **STAYED.** All `from projects.polymarket.polyquantbot.X import Y` in `main.py` are untouched. |

**What is now legacy:**
- `CMD ["python", "main.py"]` in Dockerfile — replaced by `CMD ["python", "scripts/run_api.py"]`.
- The startup print `🚀 PolyQuantBot starting (Railway)` — replaced with CrusaderBot naming.

---

## Validation Handoff

```
SENTINEL validation required for CrusaderBot Fly.io deploy readiness before merge.
Source: projects/polymarket/polyquantbot/reports/forge/phase8_1_crusaderbot_fly_readiness.md
Tier: MAJOR
```

Suggested Next Step: SENTINEL Phase 0 check → validate report path, PROJECT_STATE update, no phase*/ folders, domain structure — then run targeted validation against FastAPI startup path and Dockerfile import resolution.
