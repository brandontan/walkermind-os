# WARP•FORGE REPORT — asyncpg-pgbouncer-fix

Validation Tier: MINOR
Claim Level: NARROW INTEGRATION
Validation Target: asyncpg pool init kwarg + db_ping diagnostic surface + monitoring/health reason plumbing
Not in Scope: pool sizing changes, Postgres infra changes, additional retry/circuit logic, activation guard flips, USE_REAL_CLOB flip, any trading or order path
Suggested Next Step: WARP🔹CMD review required.

---

## 1. What was built

Production /health was flapping every ~5 minutes with the operator alert
`database: error: database reported unhealthy`. Sentry issue
`DAWN-SNOWFLAKE-1729-G` showed 681 events of
`prepared statement "__asyncpg_stmt_e7__" does not exist` plus 14
`DuplicatePreparedStatementError` (J), 10 `ProtocolViolationError`
parameter-mismatch (P), and one `ProtocolError` column-count-mismatch
(Q) — the documented signature of asyncpg's server-side prepared
statement cache colliding with PgBouncer transaction-pooling
multiplexing (https://github.com/MagicStack/asyncpg/issues/339).

Two surgical changes:

1. `database.py:init_pool()` now passes `statement_cache_size=0` to
   `asyncpg.create_pool`. This disables asyncpg's per-connection
   server-side prepared statement cache so every query is parsed
   client-side and dispatched as a simple Parse/Bind/Execute round-trip
   that survives PgBouncer's per-transaction connection multiplexing.
   Other pool kwargs (`min_size=1`, `max_size=DB_POOL_MAX`,
   `command_timeout=30`) are unchanged.

2. `database.py:ping()` now records the exception class name into a
   module-level `_last_ping_error` on the failure path and clears it
   on success. New accessor `last_ping_error()` exposes it. The
   `logger.error("DB ping failed", ...)` call gains `exc_info=True`
   so Sentry receives the structured exception (class + traceback +
   `__cause__` chain) instead of just the formatted message — the
   visibility gap that left the prior audit guessing.

3. `monitoring/health.py:_with_timeout` gains an optional
   `reason_provider: Callable[[], str | None]` keyword argument. When
   provided and the inner check returns False, the provider is
   consulted and any non-empty result is appended to the reason
   string in parentheses, producing
   `error: database reported unhealthy (DuplicatePreparedStatementError)`
   instead of the previous bare
   `error: database reported unhealthy`. `run_health_checks` wires
   `database.last_ping_error` into the database check only — the
   three other dependency checks (telegram, alchemy_rpc, alchemy_ws)
   keep their existing contracts unchanged.

The activation posture is preserved: `USE_REAL_CLOB` default False,
`ENABLE_LIVE_TRADING` / `EXECUTION_PATH_VALIDATED` /
`CAPITAL_MODE_CONFIRMED` neither read nor mutated by this change. No
trading, risk, or execution path is touched. Paper mode contract is
unaffected.

## 2. Current system architecture

```
Fly health probe (10s)
       │
       ▼
GET /health  (api/health.py)
       │
       ▼
run_health_checks()  (monitoring/health.py)
       │
       ├─► _with_timeout("database", check_database,
       │                  reason_provider=db.last_ping_error)
       │          │
       │          ▼
       │   db_ping()  (database.py)
       │          │
       │          ├─► init_pool()
       │          │     └─► asyncpg.create_pool(
       │          │             …, statement_cache_size=0)   ◄── FIX 1
       │          ├─► pool.acquire() → SELECT 1
       │          └─► except Exception as exc:
       │                 _last_ping_error = type(exc).__name__  ◄── FIX 2
       │                 logger.error(..., exc_info=True)        ◄── Sentry richness
       │                 return False
       │
       ▼  (on False)
   reason = last_ping_error() → e.g. "DuplicatePreparedStatementError"
   checks["database"] = "error: database reported unhealthy
                        (DuplicatePreparedStatementError)"
       │
       ▼
   monitoring/alerts → Telegram operator alert (now diagnosable)
```

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/database.py` — pool kwarg
  `statement_cache_size=0`; `_last_ping_error` module state;
  `ping()` captures class name + uses `exc_info=True`;
  `last_ping_error()` accessor.
- `projects/polymarket/crusaderbot/monitoring/health.py` — import
  `last_ping_error`; `_with_timeout` accepts optional
  `reason_provider`; database check passes the provider so the
  asyncpg class is appended to the unhealthy reason string.

Created:
- `projects/polymarket/crusaderbot/tests/test_database.py` — 5 hermetic
  tests:
  1. `test_init_pool_passes_statement_cache_size_zero`
  2. `test_ping_success_clears_last_error`
  3. `test_ping_failure_records_exception_class_name`
  4. `test_ping_failure_logs_with_exc_info`
  5. `test_check_database_surfaces_exception_class_in_health_reason`
- `projects/polymarket/crusaderbot/reports/forge/asyncpg-pgbouncer-fix.md`
  (this report).

State files (touched as required by the lane closure):
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- 817/817 hermetic crusaderbot tests green (was 812 before this lane;
  +5 new database tests). Local pytest run on 2026-05-10.
- Ruff clean on every changed file
  (`database.py`, `monitoring/health.py`, `tests/test_database.py`).
- Existing `tests/test_health.py` unchanged and 38/38 green —
  the `error:` prefix contract the alerts module relies on is
  preserved (the parenthetical class name is additive, not a
  replacement).
- The `bot/handlers/admin.py` `/status` caller of
  `database.ping()` continues to read it as a bool — the public
  signature of `ping()` is unchanged. Backward-compat preserved.

## 5. Known issues

- `DB_POOL_MAX=5` and the absence of
  `max_inactive_connection_lifetime` / `connect_timeout` overrides
  remain — they were called out in the prior diagnostic as STANDARD-tier
  follow-ups and are NOT in scope for this MINOR lane. If
  flaps persist after `statement_cache_size=0` reaches production,
  WARP🔹CMD can authorize a separate STANDARD lane to tune those.
- The Postgres app right-sizing question (Sentry hypothesis #3 from
  the prior audit) is unresolved by this fix and remains an operator
  / infra decision, not a code lane.
- Alert text format change is observable in Telegram: operators will
  start seeing `(SomeAsyncpgError)` after the unhealthy literal. Tests
  confirm the prefix `error: database reported unhealthy` is preserved,
  so any downstream parser that matched the prefix continues to work.

## 6. What is next

- WARP🔹CMD review + merge decision on PR.
- After merge + redeploy, watch /health and operator Telegram for one
  full Fly health-check cycle (≥ 5 min). Expected outcomes:
  1. Sentry events `DAWN-SNOWFLAKE-1729-G/J/P/Q` stop firing
     (prepared-statement names no longer used).
  2. If a residual flap occurs, the Telegram alert now includes
     the asyncpg exception class — pointing WARP🔹CMD directly at
     hypothesis #1 (Postgres-side disturbance) vs hypothesis #2
     (stale connection retention) without another Sentry trip.
- If residual flaps surface a non-prepared-statement asyncpg class,
  open WARP/CRUSADERBOT-DB-POOL-HARDENING (STANDARD) for the
  pool-tuning follow-up.
