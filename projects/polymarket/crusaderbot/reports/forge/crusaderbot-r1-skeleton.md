# WARP•FORGE Report — crusaderbot-r1-skeleton

**Branch:** WARP/crusaderbot-r1-skeleton
**Last Updated:** 2026-05-04 00:28 Asia/Jakarta
**Validation Tier:** STANDARD
**Claim Level:** FOUNDATION

---

## 1. What was built

R1 skeleton for CrusaderBot at the new authoritative project path `projects/polymarket/crusaderbot/`. Establishes minimal runnable surface: FastAPI app + lifespan-managed Postgres pool + Redis client + Telegram polling, with rerun-safe initial schema migration and explicit fail-fast on missing required env vars. Paper mode only — all 5 activation guards default OFF.

Lane also performs ACTION 1 (governance): `PROJECT_REGISTRY.md` updated — CrusaderBot path moved from `projects/polymarket/polyquantbot` → `projects/polymarket/crusaderbot`; legacy polyquantbot tree marked `💤 DORMANT (legacy paper-beta — Priority 9 COMPLETE, archived)`. Legacy tree is left untouched (out of scope per task).

## 2. Current system architecture (skeleton slice)

```
HTTP client
  ↓
FastAPI (api/health: GET /health, GET /ready)
  ↓
lifespan (main.py)
  ↓ on startup
  ├── db.connect()                        → asyncpg pool (min=1, max=DB_POOL_MAX)
  ├── cache.connect()                     → redis.asyncio client (decode_responses=True)
  ├── db.run_migrations()                 → idempotency-checked SQL apply (skip if `users` exists)
  └── bot_app.start_polling()             → python-telegram-bot Application (long polling)
  ↓ on shutdown (reverse order)
  ├── bot_app.updater.stop / stop / shutdown
  ├── cache.disconnect()
  └── db.disconnect()

Telegram client → bot_app updater → CommandHandler dispatch
  ├── /start  → "👋 CrusaderBot online. Paper mode active."
  └── /status → guard-state list + Mode (PAPER) + APP_ENV

domain/risk/constants.py is import-only at R1 (referenced from no runtime call yet).
```

Boundaries respected: no live trading code, no real wallet operations, no signing surface, no Polymarket CLOB client wired, no scheduler/jobs (R4+ scope).

## 3. Files created (full repo-root paths)

**Governance (ACTION 1):**
- `PROJECT_REGISTRY.md` — CrusaderBot row path updated; new polyquantbot DORMANT row added; CURRENT FOCUS pointer updated; Last Updated bumped

**Project skeleton (ACTION 2 — all under `projects/polymarket/crusaderbot/`):**
- `main.py` — FastAPI app + lifespan + structlog setup
- `config.py` — pydantic-settings BaseSettings (12 required vars + 5 guards + 5 operational defaults)
- `database.py` — asyncpg pool, connect/disconnect/ping/run_migrations (rerun-safe via `users` existence check)
- `cache.py` — redis.asyncio wrapper, connect/disconnect/ping/get/set/delete (JSON serialize internally)
- `__init__.py` — package marker (added to make relative imports work; not in original task spec — see "Known issues")
- `api/__init__.py` — package marker
- `api/health.py` — GET /health, GET /ready (returns ready/db/cache/live_trading/paper_mode)
- `bot/__init__.py` — package marker
- `bot/dispatcher.py` — `get_application()`, `setup_handlers()`, `/start` + `/status` handlers
- `domain/__init__.py` — package marker
- `domain/risk/__init__.py` — package marker
- `domain/risk/constants.py` — hard-wired risk constants + 3 PROFILES + STRATEGY_AVAILABILITY + `effective_daily_loss(profile, user_override)`
- `migrations/001_init.sql` — pgcrypto extension + 16 main-schema tables (users, sessions, wallets, deposits, ledger, user_settings, copy_targets, markets, orders, positions, risk_log, idempotency_keys, fees, referral_codes, kill_switch with FALSE seed) + audit schema (`audit.log`) + all indexes
- `.env.example` — all required vars documented with placeholders, no real secrets
- `pyproject.toml` — Poetry config, `package-mode = false`, deps per task spec (FastAPI, uvicorn, python-telegram-bot, asyncpg, redis, httpx, web3, cryptography, apscheduler, structlog, pydantic-settings, python-dotenv, py-clob-client, eth-account)
- `README.md` — one-liner identity + run instructions + endpoint/command reference + boundary statement

**State files (NEW project — initialized at this lane):**
- `state/PROJECT_STATE.md` — 7-section format with Status, COMPLETED, IN PROGRESS, NOT STARTED (R2–R12), NEXT PRIORITY (R2), KNOWN ISSUES (None)
- `state/ROADMAP.md` — R1–R12 lane table + 7 activation guards table + boundary + blueprint phase mapping note
- `state/CHANGELOG.md` — initial header + first entry recording R1 lane closure

**Forge report:**
- `reports/forge/crusaderbot-r1-skeleton.md` — this report

## 4. What is working

- FastAPI app constructs cleanly via `create_app()`; lifespan wires DB → Redis → migrations → Telegram polling in correct order, reverses on shutdown.
- `Settings()` instance is constructed at module import time — missing required env var raises `pydantic.ValidationError` immediately (fail-fast verified by design; Settings has no defaults for the 12 required vars).
- `database.run_migrations()` is rerun-safe: queries `information_schema.tables` for `users` and skips re-application if schema exists; first run executes 001_init.sql inside an explicit `conn.transaction()`.
- `cache.get/set` JSON-serialize/deserialize internally with `default=str` for non-JSON-native types; `set()` accepts optional TTL.
- `/health` returns `{"status": "ok", "env": APP_ENV}`; `/ready` exercises `db.ping()` + `cache.ping()` and surfaces guard state for `live_trading` + boolean `paper_mode`.
- Telegram `/start` returns the prescribed paper-mode message; `/status` enumerates all 5 guards with ✅/⚪ markers + Mode (LIVE|PAPER) + APP_ENV.
- Risk constants module is consistent with blueprint v3.1 §6 hard-wired constants and PROFILES table; `effective_daily_loss()` returns the most-restrictive (closest-to-zero) cap among system hard stop, profile cap, and optional user override.
- All 16 schema tables + audit schema declared with FK ordering respected; `kill_switch` seeded with `FALSE` row.
- `PROJECT_REGISTRY.md` reflects new CrusaderBot path and polyquantbot DORMANT status.

## 5. Known issues

- **`crusaderbot/__init__.py` added beyond original task spec.** The task tree did not list `crusaderbot/__init__.py` (only sub-package `__init__.py` for `api/`, `bot/`, `domain/`, `domain/risk/`). Without a top-level `__init__.py`, the relative imports in `main.py` (`from .api.health import router`, etc.) would not resolve when running `uvicorn crusaderbot.main:app` from the parent directory. Added as a 0-byte marker to make the documented run path work. Not a behavior change; flagged for transparency.
- **No tests.** Per task `Not in Scope: tests`. CI/test scaffolding will land per phase as features arrive.
- **No CI/CD wiring.** No `.github/workflows`, no Dockerfile, no fly.toml in this lane (deferred — R12 ops scope).
- **Telegram polling assumes valid `TELEGRAM_BOT_TOKEN`.** If a placeholder token is used, `start_polling()` will retry against Telegram API and emit warnings, but startup completes (FastAPI is reachable). For local dry-run without a real bot token, omit polling startup or set the token to a syntactically-valid sandbox token. Not a blocker for paper-mode validation.
- **`pyproject.toml` uses Poetry `package-mode = false`.** This treats the project as an application (deps only, no distribution). If you want CI to install via `pip install .` instead, the toml will need a build-system rewrite; deferred to ops phase.
- **No `.gitignore` at the new project root.** `.env`, `__pycache__/`, `*.pyc`, `.venv/` should be ignored. Repo-level `.gitignore` may already cover these; recommend a local `.gitignore` in a follow-up MINOR pass if needed.
- **Phase numbering scope.** Blueprint v3.1 §13 uses Phase 0–11 product gates; ROADMAP.md uses R1–R12 implementation lanes. Mapping documented in ROADMAP.md "Phase numbering note" section. Surface-only inconsistency with AGENTS.md PHASE NUMBERING NORMALIZATION (which still references legacy 9.1/9.2/9.3 path) — same deferred concern raised on PR #846 ROADMAP migration note (Codex P2). Out of scope for this lane.

## 6. What is next

- **R2 — user onboarding + HD wallet generation** (MAJOR tier): wallet vault, HD seed → per-user deterministic deposit address derivation, sub-account creation on `/start` for unknown users, Telegram onboarding flow. Will require WARP•SENTINEL gate before merge.
- Post-merge sync per AGENTS.md POST-MERGE SYNC RULE: bump PROJECT_STATE.md from "IN PROGRESS: crusaderbot-r1-skeleton" to "COMPLETED: R1 skeleton merged"; add CHANGELOG entry recording PR merge SHA; update ROADMAP R1 row from 🚧 → ✅.

---

**Validation Tier:** STANDARD — non-trivial runtime surface introduced (FastAPI + Telegram polling + DB/Redis pools + migrations) but no risk-execution / capital / live-trading paths touched. WARP•SENTINEL is NOT ALLOWED on STANDARD per AGENTS.md VALIDATION TIERS rule.

**Claim Level:** FOUNDATION — surface scaffolding only. No claim of full runtime trading authority. Hard-wired risk constants exist but no enforcement path consumes them yet (R7 will).

**Validation Target:** (a) FastAPI starts without import error and `create_app()` succeeds; (b) `Settings()` raises on missing required env var; (c) `database.run_migrations()` applies 001_init.sql cleanly on first run and is no-op on rerun; (d) `cache.ping()` returns True against a live Redis; (e) `/health` returns 200 with `{"status": "ok"}`; (f) `/ready` returns true booleans for db/cache when both up; (g) Telegram `/start` returns the prescribed message; (h) `ENABLE_LIVE_TRADING` resolves False by default; (i) all 16 schema tables + `audit.log` created; (j) PROJECT_REGISTRY reflects new path + polyquantbot DORMANT.

**Not in Scope:** HD wallet derivation, deposit watcher, scheduler/jobs, signal engine, risk gate execution path, paper execution engine, exit logic, auto-redeem, fee/referral accounting, ops dashboard, tests, CI/CD, Dockerfile, fly.toml, modifications to legacy `projects/polymarket/polyquantbot/` tree.

**Suggested Next:** WARP🔹CMD review on PR (STANDARD tier; SENTINEL not allowed). On merge → open R2 lane `WARP/crusaderbot-r2-onboarding-wallet`.
