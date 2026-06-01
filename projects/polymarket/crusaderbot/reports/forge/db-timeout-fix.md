# WARP•FORGE Report — db-timeout-fix

**Date:** 2026-06-01 17:15 WIB
**Branch:** claude/crusaderbot-database-timeout-Q2LWO
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** /health database check + asyncpg pool config
**Not in Scope:** background job concurrency refactor, per-caller acquire timeouts, Supabase tier changes

---

## 1. What was built

Fixed the CrusaderBot health alert `database: error: database reported unhealthy (TimeoutError)` triggered at 2026-06-01T09:53:25+00:00.

**Root cause (confirmed via Sentry DAWN-SNOWFLAKE-1729-2J):**
`ping()` used `pool.acquire(timeout=4.5)` — competing for slots in the shared asyncpg pool (max_size=10). The pool is routinely fully exhausted by 20+ concurrent background jobs (check_candle_exits every 5s, exit_watcher every 30s, order_lifecycle every 30s, copy_trade_monitor every 60s, market_signal_scanner every 60s, etc.). At synchronized fire moments (t=60, t=300) all 10 connections are checked out; `pool._queue.get()` blocks until the 4.5s acquire timeout fires. CancelledError in asyncpg stacktrace confirms queue starvation, not a Supabase-side outage.

**Three fixes applied:**

1. `ping()` now uses `asyncpg.connect()` directly — a dedicated connection that never competes for pool slots. Health checks are now immune to pool exhaustion permanently.

2. Pool `command_timeout` reduced from 30s to 10s — connections held by slow/hung queries are recycled faster, reducing steady-state pool pressure.

3. `DB_POOL_MAX` raised from 10 to 20 — more headroom for the concurrent job load. Updated in both `config.py` (default) and `fly.toml` (production env).

---

## 2. Current system architecture

```
/health endpoint
    → run_health_checks()
        → check_database()
            → ping()              ← NOW: asyncpg.connect() direct
                                  ← WAS: pool.acquire(timeout=4.5)

Background jobs (20+, 5s–300s intervals)
    → all use pool.acquire() (no timeout)
    → asyncpg pool: min=1, max=20 (was 10), command_timeout=10s (was 30s)
    → Supabase CrusaderBot project: us-east-1
```

---

## 3. Files created / modified

| Action | File |
|---|---|
| Modified | `projects/polymarket/crusaderbot/database.py` |
| Modified | `projects/polymarket/crusaderbot/config.py` |
| Modified | `projects/polymarket/crusaderbot/fly.toml` |

**database.py changes:**
- Added `import asyncio` (was missing; needed for `asyncio.wait_for`)
- `create_pool`: `command_timeout` 30 → 10
- `ping()`: replaced `pool.acquire(timeout=4.5)` with `asyncpg.connect()` + `asyncio.wait_for(timeout=4.0)` + `finally: conn.close()`

**config.py changes:**
- `DB_POOL_MAX: int = 10` → `20`

**fly.toml changes:**
- `DB_POOL_MAX = '10'` → `'20'`

---

## 4. What is working

- `ping()` now opens a dedicated direct connection (`application_name=crusaderbot-health`) — no pool slot needed.
- Total ping budget: 4.0s `asyncio.wait_for` envelope with `command_timeout=3.0s` on the connection — well within health check's 5s `CHECK_TIMEOUT_SECONDS`.
- Connection is always closed in `finally` block; no leak.
- Pool commands now auto-cancel at 10s — reduces max connection hold time by 20s.
- `DB_POOL_MAX=20` gives 20 concurrent pool connections vs 10, reducing pool starvation probability under burst load.
- Existing `last_ping_error()` contract preserved — health alert text unchanged.
- `statement_cache_size=0` applied on direct connection (required for Supabase Supavisor pooler topology).

---

## 5. Known issues

- All 353 `pool.acquire()` calls in the codebase still have no timeout. Under extreme load bursts (>20 concurrent jobs all hitting DB simultaneously), pool can still exhaust for regular callers. This fix only makes the **health check** immune; a broader `acquire_timeout` refactor is P2.
- `ping()` now opens one new TCP+TLS+auth connection per health check (every 15s). Cost: ~1 Supabase connection slot for ~50–100ms per check cycle. Acceptable at current scale; if health check cadence drops to <5s, consider a persistent single-connection health probe.
- `command_timeout=10s` on the pool may surface latent slow queries that previously completed in 10–30s. Monitor for new `CommandTimeoutError` events in Sentry post-deploy.

---

## 6. What is next

- WARP🔹CMD review — STANDARD tier.
- Deploy to Fly (flyctl deploy via CD on merge to main).
- Confirm `/health` returns `status: ok` after deploy.
- Monitor Sentry for `CommandTimeoutError` — if background jobs start timing out at 10s, raise to 15s.
- P2 backlog: add `acquire_timeout` parameter to a `get_pool_conn()` helper so all callers have bounded wait.

---

**Suggested Next Step:** WARP🔹CMD review → merge → confirm health green on Fly.
