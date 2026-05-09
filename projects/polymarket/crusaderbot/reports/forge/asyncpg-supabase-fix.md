# WARP•FORGE REPORT — asyncpg-supabase-fix

Validation Tier: MINOR
Claim Level: NARROW INTEGRATION
Validation Target: asyncpg pool init kwargs (statement_cache_size + server_settings) + Supavisor pooler-awareness diagnostic warning + db_ping diagnostic surface + monitoring/health reason plumbing
Not in Scope: pool sizing changes, DSN topology changes (operator-owned Fly secret), additional retry/circuit logic, activation guard flips, USE_REAL_CLOB flip, any trading or order path
Suggested Next Step: WARP🔹CMD review required.

Supersedes: WARP/CRUSADERBOT-ASYNCPG-PGBOUNCER-FIX (PR #922) — this lane is the Supabase-Supavisor-aware refinement of the same fix.

---

## 1. What was built

Production /health was flapping every ~5 minutes with the operator
alert `database: error: database reported unhealthy`. Sentry showed
the documented signature of asyncpg's per-connection prepared
statement cache colliding with transaction-pool multiplexing:

| Sentry issue | Events | Symptom |
| --- | --- | --- |
| DAWN-SNOWFLAKE-1729-G | 681 | `prepared statement "__asyncpg_stmt_*__" does not exist` |
| DAWN-SNOWFLAKE-1729-J | 14 | `DuplicatePreparedStatementError` |
| DAWN-SNOWFLAKE-1729-P | 10 | `ProtocolViolationError` parameter mismatch |
| DAWN-SNOWFLAKE-1729-Q | 1 | `ProtocolError` column count mismatch |
| DAWN-SNOWFLAKE-1729-E | 1 | `kill_switch` read failed in `/ops` |

Database backend is Supabase Postgres fronted by Supavisor — Supabase's
managed pgbouncer-style proxy. Supavisor exposes two pools per project:

| Pool | Default port | Pooling mode | asyncpg prepared cache safe? |
| --- | --- | --- | --- |
| Transaction pool | 6543 | per-transaction multiplexing | NO |
| Session pool     | 5432 | per-session sticky           | YES |
| Direct           | 5432 (database host, not pooler.supabase) | direct | YES |

Production DSN almost certainly resolves to the transaction pool
(host suffix `pooler.supabase.com`, port `6543`) — that is the default
recommended in the Supabase dashboard for serverless / edge / Fly
workloads. asyncpg's server-side prepared statement cache leases names
per backend connection; Supavisor reassigns the underlying backend
between transactions, so the next acquire lands on a different backend
where the cached statement name does not exist. The error surfaces are
exactly the four DAWN-SNOWFLAKE classes above.

Three surgical changes:

1. `database.py:init_pool()` now passes two new kwargs to
   `asyncpg.create_pool`:
   - `statement_cache_size=0` — disables the per-connection
     server-side prepared statement cache so every query is parsed
     client-side and dispatched as a simple Parse/Bind/Execute round
     trip that survives Supavisor's per-transaction connection
     multiplexing. References:
     https://github.com/MagicStack/asyncpg/issues/339 ;
     https://github.com/orgs/supabase/discussions/12733
   - `server_settings={"application_name": "crusaderbot"}` — labels
     every backend connection so an operator running
     `SELECT * FROM pg_stat_activity WHERE application_name='crusaderbot'`
     in the Supabase SQL editor (or against Postgres directly) can
     immediately distinguish bot sessions from psql / Studio / other
     workloads sharing the same project. Pure observability — has zero
     functional impact on query execution.

2. `database.py` adds `_warn_if_supavisor_transaction_pool(dsn)` —
   a diagnostic helper called at the top of `init_pool()`. When the
   DSN host contains the substring `pooler.supabase` AND port equals
   `6543`, it emits a single WARNING-level log line documenting the
   pooler topology and pointing operators at the session pooler /
   direct connection alternatives if session-only features
   (LISTEN/NOTIFY, SET SESSION, advisory locks) are needed. The check
   is purely informational — startup is never blocked, parse failures
   are silently ignored. This warning correlates the DSN topology
   with /health flap events so an operator on a legacy DSN can see
   the relationship without triaging Sentry.

3. `database.py:ping()` failure path captures the exception class name
   into module-level `_last_ping_error` (cleared on success). New
   accessor `last_ping_error()` exposes it. The
   `logger.error("DB ping failed", ...)` call gains `exc_info=True`
   so Sentry receives the structured exception (class + traceback +
   `__cause__` chain) instead of just the formatted message.

4. `monitoring/health.py:_with_timeout` gains an optional
   `reason_provider: Callable[[], str | None]` keyword argument. When
   provided and the inner check returns False, the provider is
   consulted and any non-empty result is appended to the reason
   string in parentheses, producing
   `error: database reported unhealthy (DuplicatePreparedStatementError)`
   instead of the previous bare `error: database reported unhealthy`.
   `run_health_checks` wires `database.last_ping_error` into the
   database check only — telegram, alchemy_rpc, and alchemy_ws keep
   their existing contracts unchanged.

Activation posture is preserved: `USE_REAL_CLOB` default False,
`ENABLE_LIVE_TRADING` / `EXECUTION_PATH_VALIDATED` /
`CAPITAL_MODE_CONFIRMED` neither read nor mutated. No trading, risk,
or execution path is touched. Paper mode contract is unaffected.

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
       │          │     ├─► _warn_if_supavisor_transaction_pool(DSN)   ◄── FIX 2
       │          │     └─► asyncpg.create_pool(
       │          │             …,
       │          │             statement_cache_size=0,                ◄── FIX 1
       │          │             server_settings={                       ◄── FIX 1
       │          │                 "application_name": "crusaderbot",
       │          │             })
       │          ├─► pool.acquire() → SELECT 1
       │          └─► except Exception as exc:
       │                 _last_ping_error = type(exc).__name__          ◄── FIX 3
       │                 logger.error(..., exc_info=True)               ◄── Sentry richness
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
- `projects/polymarket/crusaderbot/database.py` — pool kwargs
  `statement_cache_size=0` + `server_settings={"application_name": "crusaderbot"}`;
  `_warn_if_supavisor_transaction_pool` diagnostic;
  `_last_ping_error` module state;
  `ping()` captures class name + uses `exc_info=True`;
  `last_ping_error()` accessor.
- `projects/polymarket/crusaderbot/monitoring/health.py` — import
  `last_ping_error`; `_with_timeout` accepts optional
  `reason_provider`; database check passes the provider so the
  asyncpg class is appended to the unhealthy reason string.

Created:
- `projects/polymarket/crusaderbot/tests/test_database.py` — 10
  hermetic tests:
  1. `test_init_pool_passes_statement_cache_size_zero`
  2. `test_init_pool_passes_application_name_server_setting`
  3. `test_init_pool_warns_when_supavisor_transaction_pool`
  4. `test_init_pool_does_not_warn_for_session_pool_port`
  5. `test_init_pool_does_not_warn_for_non_supabase_host`
  6. `test_init_pool_diagnostic_does_not_crash_on_malformed_dsn`
  7. `test_ping_success_clears_last_error`
  8. `test_ping_failure_records_exception_class_name`
  9. `test_ping_failure_logs_with_exc_info`
  10. `test_check_database_surfaces_exception_class_in_health_reason`
- `projects/polymarket/crusaderbot/reports/forge/asyncpg-supabase-fix.md`
  (this report).

State files (touched as required by the lane closure):
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- 822/822 hermetic crusaderbot tests green (812 baseline + 10 new
  database tests). Local pytest run.
- Ruff clean on every changed file
  (`database.py`, `monitoring/health.py`, `tests/test_database.py`).
- Existing 38/38 `test_health.py` tests preserved unchanged — the
  `error:` prefix contract the alerts module relies on is preserved
  (parenthetical class name is additive, not a replacement).
- The `bot/handlers/admin.py` `/status` caller of
  `database.ping()` continues to read it as a bool — the public
  signature of `ping()` is unchanged. Backward compatibility
  preserved.

## 5. Known issues

- `DB_POOL_MAX=5` and the absence of
  `max_inactive_connection_lifetime` / `connect_timeout` overrides
  remain — these were called out in the diagnostic as STANDARD-tier
  follow-ups and are NOT in scope for this MINOR lane. If flaps
  persist after this PR reaches production with the asyncpg class
  visible in the alert text, WARP🔹CMD can authorize a separate
  STANDARD lane to tune those.
- Alert text format change is observable in Telegram: operators will
  start seeing `(SomeAsyncpgError)` after the unhealthy literal. The
  test suite confirms the prefix `error: database reported unhealthy`
  is preserved, so any downstream parser that matched the prefix
  continues to work.
- The Supavisor warning fires once per process boot per pool init.
  There is no rate limiting because the function only runs on the
  cold init path; this is intentional.

## 6. Alternative DSN topologies (operator decision, not in scope)

This PR is a code-only fix. If after deploy the operator wants to
move off the transaction pool entirely, three alternatives exist —
each is an operator action against `DATABASE_URL` (Fly secret), not
a code change:

| Option | DSN shape | Pros | Cons |
| --- | --- | --- | --- |
| Stay on transaction pool (this PR) | `…pooler.supabase.com:6543/…` | High connection density; Supabase's recommended default for serverless | Loses session-only features (LISTEN/NOTIFY, SET SESSION, advisory locks) |
| Switch to session pooler | `…pooler.supabase.com:5432/…` | Prepared statement cache works; session features preserved | Lower connection density (one client per backend); some Supabase limits |
| Direct connection | `…<project>.supabase.co:5432/…` | Full Postgres feature set | No pooling — bot needs to be conservative with connection counts |

Recommendation: keep the transaction pool DSN. CrusaderBot does not
use LISTEN/NOTIFY, advisory locks, or session-scoped settings, so
the transaction pool is the right shape. `statement_cache_size=0`
is the correct fix; the alternative DSN topologies are documented
here purely so the operator has the background if a future use-case
needs session features.

## 7. What is next

- WARP🔹CMD review + merge decision on this PR.
- Close PR #922 (`WARP/CRUSADERBOT-ASYNCPG-PGBOUNCER-FIX`) as
  superseded by this PR; the new lane subsumes the old one and adds
  Supavisor-specific contracts.
- After merge + redeploy, watch /health and operator Telegram for one
  full Fly health-check cycle (≥ 5 min). Expected outcomes:
  1. Sentry events DAWN-SNOWFLAKE-1729-G/J/P/Q stop firing
     (prepared-statement names no longer used).
  2. If a residual flap occurs, the Telegram alert now includes
     the asyncpg exception class — pointing WARP🔹CMD directly at
     the failure mode (Postgres-side disturbance vs stale-connection
     retention vs server-side max_connections) without another
     Sentry triage step.
  3. Supabase SQL editor running
     `SELECT count(*) FROM pg_stat_activity WHERE application_name='crusaderbot'`
     returns the pool's current backend count.
- If residual flaps surface a non-prepared-statement asyncpg class,
  open WARP/CRUSADERBOT-DB-POOL-HARDENING (STANDARD) for the
  pool-tuning follow-up.
