# WARP•R00T FORGE REPORT — root-db-boot-resilience

Branch: `WARP/root-db-boot-resilience`
Role: WARP•R00T (owner-directed 2026-06-07 — "Restart + ship hardening" after the prod DB-health incident)
Validation Tier: **MAJOR** (async core / DB connection layer)
Claim Level: NARROW INTEGRATION
Validation Target: The asyncpg pool boot path tolerates a transient Supabase/Supavisor connect stall — a hung warm-ping fails fast, and create_pool retries with backoff — so a flaky boot no longer wedges the event loop / freezes /health (the 2026-06-07 21:17 incident).
Not in Scope: trading/risk logic; the lifespan startup ordering in main.py; Supabase/Fly infra config; the health-alert dispatcher thresholds (already debounced).
Suggested Next Step: merge → CD redeploys → confirm /health stays ok across the deploy reboot.

---

## 1. Incident (what happened)

After the #1696/#1698 merge CD deploy (release v1225, machine `185d67db504d68`,
2026-06-07 21:17 UTC), the bot booted but `/health` reported
`database: error: database reported unhealthy (TimeoutError)` and then **froze**
(health check stuck at 21:19:08, `ready:false`) — the event loop wedged on the
boot-time DB connect. Telegram operator pages fired at 21:19 and 21:24. No
trades after 21:17.

Diagnosis (live):
- Postgres server-side: **healthy** — no errors, no slow queries, no locks (only
  normal checkpoints in the logs).
- Supavisor pooler: healthy (4 idle backends, not saturated).
- The runtime code delta from the previously-healthy v1222 was nil (#1696 is
  byte-identical, #1698 is test-only) → **not a code regression**; this is the
  documented recurring "prod can't connect to Supabase at boot" stall.
- Recovery: an owner-authorized Fly machine restart cleared it immediately
  (`{"status":"ok","database":"ok"}` on first poll).

## 2. Root-cause mechanism + fix

The boot warm-ping and pool creation were **unbounded / non-retrying**, so a
single transient connect stall could wedge the loop with no self-heal:

1. `_init_connection` ran `await conn.execute("SELECT 1")` on every new backend
   with **no timeout**. A hung/recycled Supabase backend whose `SELECT 1` stalls
   blocks the acquiring coroutine (incl. the /health ping's `pool.acquire`).
   → **Fix:** wrap it in `asyncio.wait_for(..., timeout=_INIT_PING_TIMEOUT=5s)`
   so a bad backend fails fast and asyncpg opens a fresh one.
2. `init_pool()` called `asyncpg.create_pool(...)` **once**; a transient boot
   connect blip yields a broken/abandoned pool.
   → **Fix:** bounded connect-retry with exponential backoff
   (`_POOL_CONNECT_ATTEMPTS=5`, 1→16s), retrying only connectivity-class errors
   (`OSError`, `asyncio.TimeoutError`, `asyncpg.PostgresError`); after the budget
   is exhausted it **re-raises** (no silent failure) so the process exits and Fly
   restarts it cleanly instead of running DB-blind.
3. Churn reduction: `min_size` 1→**2** (a warm spare so the /health ping can
   always acquire even while the scan loop holds a connection) and
   `max_inactive_connection_lifetime` 60→**300s** (fewer cold reconnects → less
   warm-ping stall surface).

## 3. Current system architecture

`database.init_pool()` is now boot-resilient and self-healing on transient
connect failures; `_init_connection` is bounded. No change to the query path,
the pool's runtime semantics (`statement_cache_size=0`, `command_timeout=30`,
`application_name`), or any trading/risk code.

## 4. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/database.py` — `import asyncio`; boot-resilience constants; bounded `_init_connection`; retry/backoff `init_pool` + min_size 2 / inactive-lifetime 300.
- `projects/polymarket/crusaderbot/tests/test_database.py` — updated the pool-contract assertion (min_size 2, inactive-lifetime 300) + 4 new tests (warm-ping timeout fail-fast & pass-through; retry-then-succeed; re-raise-after-exhaustion).
- state: `state/PROJECT_STATE.md`, `state/CHANGELOG.md`.

## 5. What is working

- 15 `test_database.py` tests pass (existing contract + 4 new boot-resilience).
- ruff + py_compile clean.
- Prod recovered via the restart and is healthy (`/health` ok, mode paper).

## 6. Known issues

- The underlying flakiness is in the Supabase/Supavisor connect at boot
  (operational); this lane makes the app **survive** it rather than eliminate
  the infra blip. If create_pool fails all 5 attempts, the process exits and Fly
  restarts (clean loop) — acceptable, surfaced via logs.
- `/health` could not be curled from the CC sandbox (egress); current health was
  confirmed via the Fly Machines API health check.

## 7. What is next

Merge → CD redeploys → confirm `/health` stays `ok` through the deploy reboot
(the exact scenario that failed). If a future boot still stalls, the retry now
self-heals or restarts cleanly instead of wedging.

---

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: boot-time DB connect tolerates transient stalls (bounded warm-ping + retrying create_pool); no event-loop wedge.
Not in Scope: trading/risk logic, infra config, lifespan ordering, alert thresholds.
Suggested Next Step: merge → verify /health across the CD reboot.
