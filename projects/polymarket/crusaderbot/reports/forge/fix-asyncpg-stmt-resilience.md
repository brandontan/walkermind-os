# WARP•FORGE Report — fix-asyncpg-stmt-resilience

**Branch:** WARP/fix-asyncpg-stmt-resilience
**Date:** 2026-05-12
**Tier:** MAJOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** asyncpg connection pool configuration in database.py init_pool()
**Not in Scope:** query-level retry wrappers, job execution paths, risk/execution pipeline, migration SQL
**Suggested Next Step:** WARP•SENTINEL validation required before merge

---

## 1. What Was Built

Added `_init_connection` warm-ping to the asyncpg pool so every new physical backend connection is probed with `SELECT 1` at creation time. This surfaces broken or stale connections (e.g. Supabase idle-timeout recycled backends) immediately at pool-init rather than mid-request, preventing silent dead connections from reaching the `/health` DB ping path or job write paths.

**Context on Sentry events DAWN-SNOWFLAKE-1729-5 through -9, -G, -X (7,000+ events):**

The root cause of `InvalidSQLStatementNameError`, `DuplicatePreparedStatementError`, and `ProtocolViolationError` was asyncpg's per-connection prepared statement cache being out-of-sync with the backend after Supabase/PgBouncer recycled connections. The primary fix — `statement_cache_size=0` — was **already applied** in a prior hotfix (commit `4f58645`, PR #985). With the cache disabled, prepared statement names are never cached client-side and cannot become orphaned.

This PR adds the `init=_init_connection` warmup as the remaining defensive layer from the TASK-2 spec. The warm-ping ensures pool connections are validated at creation, providing early failure detection on the pool init path.

The `execute_with_retry` wrapper for individual query call sites was evaluated and **deferred**: with `statement_cache_size=0` in place, the error classes it would retry cannot occur. Adding per-call-site wrappers would introduce abstractions for errors that no longer surface.

---

## 2. Current System Architecture

Connection pool config (after this PR):

```
statement_cache_size=0   — disables prepared stmt cache (main fix, already present)
init=_init_connection    — warm SELECT 1 on each new physical connection (this PR)
command_timeout=30       — hard timeout per query
min_size=1, max_size=DB_POOL_MAX
application_name="crusaderbot"
```

---

## 3. Files Created / Modified

| Action | Path |
|---|---|
| Modified | `projects/polymarket/crusaderbot/database.py` |
| Created  | `projects/polymarket/crusaderbot/reports/forge/fix-asyncpg-stmt-resilience.md` |

---

## 4. What Is Working

- `statement_cache_size=0` already prevents `InvalidSQLStatementNameError` / `DuplicatePreparedStatementError` / `ProtocolViolationError` from occurring (in place since PR #985).
- `_init_connection` now validates each physical backend connection at pool creation. A dead backend surfaces as a pool init failure (logged, app aborts) rather than a silent error mid-request.
- Pool setup is fully idempotent — `init_pool()` checks `_pool is not None` before creating.

---

## 5. Known Issues

- `execute_with_retry` wrapper for critical job paths deferred — not required while `statement_cache_size=0` prevents the target error classes.
- PgBouncer transaction-mode is still incompatible with asyncpg in general (session mode required). This is a deployment constraint documented in TASK-2 notes, not a code issue.

---

## 6. What Is Next

WARP•SENTINEL validation required for `fix-asyncpg-stmt-resilience` before merge.
Source: `projects/polymarket/crusaderbot/reports/forge/fix-asyncpg-stmt-resilience.md`
Tier: MAJOR
