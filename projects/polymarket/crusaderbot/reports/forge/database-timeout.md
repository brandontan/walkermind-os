# WARP•FORGE Report — database-timeout

**Validation Tier:** MINOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** asyncpg pool health-check timeout chain
**Not in Scope:** Supabase infra configuration, Fly.io network policy, other health checks
**Suggested Next Step:** Deploy via `flyctl deploy`; confirm `/health` returns `status:"ok"` within 60 seconds

---

## 1. What was built

Fixed `database: error: database timeout after 3s` health alert that was taking CrusaderBot to `status: down`.

Three-point fix to the DB health-check timeout chain:

- `monitoring/health.py`: raised `CHECK_TIMEOUT_SECONDS` 3.0 → 5.0 — gives a 5-second budget instead of 3 (Fly HTTP check timeout is 10s, so headroom is preserved)
- `database.py` `ping()`: added `timeout=4.5` to `pool.acquire()` — caps pool acquisition at 4.5s; if no connection is available in time, `ping()` returns `False` immediately with `_last_ping_error = "TimeoutError"` rather than being cut by the outer `asyncio.wait_for`
- `database.py` `init_pool()`: added `timeout=10` to `asyncpg.create_pool()` — limits each new physical TCP connection setup (TLS + auth) to 10 seconds instead of the OS default (~2 min), preventing pool-level hangs on Supabase reconnects

---

## 2. Current system architecture

Health check chain (unchanged structure, fixed budget):

```
Fly HTTP check (every 15s, 10s timeout)
  → GET /health (api/health.py)
    → run_health_checks() (monitoring/health.py)
      → asyncio.wait_for(check_database(), timeout=5.0)   ← was 3.0
        → ping() (database.py)
          → pool.acquire(timeout=4.5)                     ← was unbounded
            → conn.fetchval("SELECT 1")
```

Pool config (database.py):
- `asyncpg.create_pool(timeout=10, ...)` — TCP setup capped at 10s per connection
- `command_timeout=30` — individual query timeout unchanged
- `min_size=1, max_size=10` — unchanged

---

## 3. Files created / modified

| Action | Path |
|---|---|
| Modified | `projects/polymarket/crusaderbot/monitoring/health.py` |
| Modified | `projects/polymarket/crusaderbot/database.py` |
| Modified | `projects/polymarket/crusaderbot/tests/test_database.py` |
| Created  | `projects/polymarket/crusaderbot/reports/forge/database-timeout.md` |

---

## 4. What is working

- All 11 `test_database.py` tests pass
- `_FakePool.acquire()` updated to accept `timeout=None` kwarg — no regression in ping tests
- `CHECK_TIMEOUT_SECONDS = 5.0` verified in health.py
- `pool.acquire(timeout=4.5)` and `create_pool(..., timeout=10, ...)` verified in database.py

---

## 5. Known issues

- The `test_health.py` suite cannot run in this container due to a system-level `cffi`/`cryptography` package conflict (unrelated to this fix; pre-existing environment issue). Database tests are fully green.
- Root cause of production DB slowness (Supabase latency spike, stale connection, etc.) is external — this fix ensures the health check budget is large enough to survive reconnection scenarios.

---

## 6. What is next

- Deploy to Fly.io (`flyctl deploy` or merge triggers CD)
- Confirm `/health` returns `status: "ok"` within 60 seconds post-deploy
- Monitor Telegram operator alerts for recurrence; if DB is still timing out at 5s, the issue is infra-level (Supabase project paused, DSN misconfigured, network partition)
