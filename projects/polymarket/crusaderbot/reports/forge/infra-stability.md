# WARP•FORGE Report — Infra Stability

- Branch: `WARP/CRUSADERBOT-INFRA-STABILITY`
- Linear: WARP-39 (Lane 1 — Infra Stability), blocks WARP-40 (Lane 2 — Runtime Bugfix)
- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Validation Target: every `asyncpg.connect`/`create_pool` path disables the prepared-statement cache; Fly single-instance enforcement; DB pool limits + clean shutdown + pool-reusing health check; startup env validation lists all missing vars.
- Not in Scope: WARP-40 runtime bugfixes (exit_watch type bug, access_tier schema, signal_scan crash); any live-trading guard change; applying migrations; running `fly` commands.
- Suggested Next Step: WARP•SENTINEL MAJOR audit of this PR, then WARP🔹CMD merge + Fly.io operator steps below, then open WARP-40.

---

## 1. What was built

WARP-39 is a Sentry infra-burn lane (~10k DB errors + multi-instance Telegram conflict). On inspection, the two live runtime asyncpg paths and three of the four fixes were already implemented by prior PRs. This lane closes the genuine remaining gaps and verifies the rest against code (file:line evidence below).

Changes made (3 files):

- FIX 1 — `statement_cache_size=0` added to the two one-off operator scripts that still opened raw connections without it:
  - `scripts/cleanup_demo_data.py:208`
  - `scripts/seed_demo_data.py:469`
- FIX 2 — `max_machines_running = 1` added to `fly.toml` `[http_service]` to cap autostart at a single machine (complements existing `min_machines_running = 1`, `auto_stop_machines = false`, `[deploy] strategy = "immediate"`).

Verified already-satisfied (no change):

- FIX 1 (runtime paths): `database.py:101` pool and `webtrader/backend/sse.py:86` LISTEN connection already pass `statement_cache_size=0`.
- FIX 2 (code side): `main.py:127` already uses `start_polling(drop_pending_updates=True)`; `fly.toml` already has `[deploy] strategy = "immediate"`.
- FIX 3: pool min/max explicitly set at `database.py:97-98` (`min_size=1`, `max_size=settings.DB_POOL_MAX`; `DB_POOL_MAX=5` in `fly.toml` — more conservative than the task's illustrative `max=10`); pool closed cleanly in the lifespan `finally` at `main.py:262` (`close_pool()`); health probe `ping()` reuses the pool via `pool.acquire()` at `database.py:148-169`.
- FIX 4: `validate_required_env()` at `config.py:307` already returns the full list of ALL missing required vars at once, logs one ERROR per missing key (key names only — values never logged), and the boot path (`main.py:62`) surfaces the degraded state via `/health` instead of crashing on the first missing var.

## 2. Current system architecture

- DB access: single asyncpg pool created in `database.py:init_pool()` with `statement_cache_size=0`, `min_size`/`max_size`, `command_timeout`, warm-ping `init`, and `application_name` server setting; lifecycle owned by `main.py:lifespan` (open at startup, `close_pool()` in `finally`). SSE uses one dedicated direct LISTEN connection (`sse.py`), also `statement_cache_size=0`. Operator scripts open transient connections, now also `statement_cache_size=0`.
- Telegram: PTB application; polling mode uses `drop_pending_updates=True`. Single-instance enforced operationally by Fly (`max_machines_running = 1`, immediate deploy strategy, operator `fly scale count 1`).
- Config: `validate_required_env()` is fail-soft (logs all missing, continues) so `/health` can report degraded configuration.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/scripts/cleanup_demo_data.py` (modified — `statement_cache_size=0`)
- `projects/polymarket/crusaderbot/scripts/seed_demo_data.py` (modified — `statement_cache_size=0`)
- `projects/polymarket/crusaderbot/fly.toml` (modified — `max_machines_running = 1`)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` (state sync — 4 sections)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` (lane entry)
- `projects/polymarket/crusaderbot/reports/forge/infra-stability.md` (this report)

## 4. What is working

- Every `asyncpg.connect`/`create_pool` call in the package (excluding tests) now passes `statement_cache_size=0`: `database.py:95`, `sse.py:84`, `scripts/cleanup_demo_data.py:208`, `scripts/seed_demo_data.py:469` (confirmed via repo-wide grep; `config.py:268` is a comment only).
- `fly.toml` caps running machines at 1 and deploys in place (immediate), reducing the window where two machines could both poll Telegram.
- Pool limits, clean shutdown, pool-reusing health check, and all-at-once env validation confirmed present in code.

## 5. Known issues

- Pool sizing differs from the task's illustrative `min_size=2, max_size=10`: current is `min_size=1, max_size=DB_POOL_MAX(=5)`, deliberately kept because it is MORE conservative and the explicit goal of FIX 3 is to avoid `TooManyConnectionsError`. Flagged for WARP🔹CMD/SENTINEL; not changed.
- Single-instance enforcement is partly operational: `fly.toml` caps autostart, but the authoritative reduction to one machine is the operator `fly scale count 1` step (cannot run `fly` from this environment).
- Runtime not exercised here (asyncpg/telegram/`fly` unavailable in the remote container — same posture as recent lanes). Script edits are mechanical kwarg additions; `fly.toml` is config-only.

## 6. What is next

- WARP•SENTINEL MAJOR audit of this PR (Sentry IDs DAWN-6/7/8/9/A/D/G/J/P/X, DAWN-14, DAWN-1C, DAWN-2/3/4).
- After SENTINEL clears and WARP🔹CMD merges, operator post-merge steps:
  - `fly scale count 1`
  - `fly secrets set WALLET_HD_SEED="$(python -c 'import secrets; print(secrets.token_hex(32))')"`
  - Fly.io redeploy.
- Then open WARP-40 (Lane 2 — Runtime Bugfix), which is blocked by this lane.
