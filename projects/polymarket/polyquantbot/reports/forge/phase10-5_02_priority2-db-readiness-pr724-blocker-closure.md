# FORGE-X Report — phase10-5_02_priority2-db-readiness-pr724-blocker-closure

- Timestamp: 2026-04-23 06:49 (Asia/Jakarta)
- Branch: feature/close-pr-#724-blockers-for-db-readiness
- PR lane: #724

## 1) What was built
- Hardened control-plane startup in `projects/polymarket/polyquantbot/server/main.py` to initialize DB runtime explicitly through `DatabaseClient.connect_with_retry(...)`, run startup healthcheck, and preserve bounded retry semantics without premature outer-timeout cutoff.
- Added deterministic pre-yield cleanup path so DB client/pool is closed when startup fails before `yield` (including Telegram startup failure after DB startup success).
- Extended runtime state and `/ready` payload to expose DB dependency truth (`required/enabled/connected/healthcheck_ok/retry config/last_error`) and gate readiness status when DB is required.
- Added `DatabaseClient.healthcheck()` to the authoritative DB implementation and replaced `projects/polymarket/polyquantbot/infra/db.py` with a compatibility shim importing from `projects/polymarket/polyquantbot/infra/db/database.py` to neutralize split-brain implementation risk.
- Added/updated runtime-surface tests for startup success, pre-yield failure cleanup, bounded timeout alignment, and readiness behavior for DB available/unavailable paths.

## 2) Current system architecture (relevant slice)
- Control-plane startup order (narrow integration scope):
  1. `run_startup_validation(...)`
  2. `_start_database_runtime(...)`
  3. `_start_telegram_runtime(...)`
  4. `yield`
- DB runtime startup:
  - Reads runtime toggles: `CRUSADER_DB_RUNTIME_ENABLED`, `CRUSADER_DB_RUNTIME_REQUIRED`.
  - Reads bounded retry knobs: `CRUSADER_DB_CONNECT_MAX_ATTEMPTS`, `CRUSADER_DB_CONNECT_BASE_BACKOFF_S`, `CRUSADER_DB_CONNECT_TIMEOUT_S`.
  - Computes retry budget and adjusts outer timeout upward when configured timeout is too small, preventing premature outer cancellation of the internal bounded retry path.
  - Runs `connect_with_retry(...)` + `healthcheck()` and records state.
- Shutdown/cleanup:
  - DB client cleanup now runs in lifespan `finally`, covering pre-yield failures and normal shutdown.

## 3) Files created / modified (full repo-root paths)
- `projects/polymarket/polyquantbot/server/main.py`
- `projects/polymarket/polyquantbot/server/api/routes.py`
- `projects/polymarket/polyquantbot/server/core/runtime.py`
- `projects/polymarket/polyquantbot/infra/db/database.py`
- `projects/polymarket/polyquantbot/infra/db.py`
- `projects/polymarket/polyquantbot/tests/test_crusader_runtime_surface.py`

## 4) What is working
- Startup DB client contract now targets authoritative package surface and no longer relies on a duplicate module implementation.
- Bounded DB retry path is preserved under an aligned outer timeout (auto-adjusted upward when needed).
- Pre-yield startup failure path closes DB client/pool before process exits startup path.
- `/ready` reflects DB dependency truth through `readiness.db_runtime` and participates in readiness status when DB is required.
- Test coverage updated for the required startup/readiness scenarios in the control-plane runtime surface suite.
- Runtime-surface validation now executed in dependency-complete environment: `pytest -q projects/polymarket/polyquantbot/tests/test_crusader_runtime_surface.py` => `19 passed`.

## 5) Known issues
- None for this scoped blocker-closure pass; runtime-surface test dependency gate is closed and the touched suite executes in the current environment.

## 6) What is next
- Required next gate: SENTINEL MAJOR validation on this source branch before merge decision.

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : Priority 2 DB readiness + startup handling path in control-plane runtime
Not in Scope      : broader DB architecture rewrite, unrelated persistence refactors, non-blocking cleanup outside PR #724 lane
Suggested Next    : SENTINEL validation on branch `feature/close-pr-#724-blockers-for-db-readiness`
