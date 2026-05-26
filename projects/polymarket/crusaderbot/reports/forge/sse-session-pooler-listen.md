# WARP•FORGE — SSE Listener Session-Pooler Fix

**Branch:** WARP/R00T-sse-session-pooler-listen
**Date:** 2026-05-26 17:15 WIB
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION

---

## 1. What was built

Fixed a production regression where the WebTrader SSE LISTEN/NOTIFY listener
reconnect-looped forever with `[Errno 111] Connection refused` (103 occurrences
since 2026-05-25, status "regressed" in Sentry DAWN-SNOWFLAKE-1729-23).

Root cause: `_normalize_dsn_for_listen()` in `webtrader/backend/sse.py`
unconditionally rewrote any Supabase pooler URL to the direct endpoint
`db.<project_ref>.supabase.co:5432`. After the operator switched `DATABASE_URL`
to the Supabase Session Pooler (to resolve the earlier TooManyConnectionsError),
that rewrite pointed the listener at the direct host — which Supabase has
disabled for direct IPv4 connections on the free tier. Every connect attempt
was refused, so no real-time events (fills, positions, scanner ticks) reached
connected WebTrader clients.

The fix keeps the listener on the pooler host and only switches the
transaction-mode port (6543) to the session-mode port (5432). The session
pooler holds a dedicated backend per client session and fully supports
LISTEN/NOTIFY. A DSN already on session port 5432 is used as-is.

## 2. Current system architecture

```
DATABASE_URL (Supabase Session Pooler, pooler host :5432)
        │
        ├── main asyncpg pool (DB_POOL_MAX=3) — general queries
        │
        └── SSE listener (DEDICATED connection)
                 _normalize_dsn_for_listen(dsn):
                   pooler host + :6543  → pooler host + :5432  (switch to session)
                   pooler host + :5432  → unchanged            (already session)
                   other host  + :6543  → other host  + :5432
                   other host  + :5432  → unchanged
                 asyncpg.connect → LISTEN on CHANNEL_MAP channels
                   → fan-out to _user_queues → SSE stream
```

No direct `db.<ref>.supabase.co` endpoint is ever used.

## 3. Files created / modified

- Modified: `projects/polymarket/crusaderbot/webtrader/backend/sse.py`
  - rewrote `_normalize_dsn_for_listen()` (no direct-host rewrite; session-port switch only)
  - removed now-unused `import re`
- Created: `projects/polymarket/crusaderbot/tests/test_sse_listen_dsn.py` (5 tests)
- Modified: `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- Modified: `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- 5 new hermetic tests pass (session-as-is, transaction→session, never-direct, non-supabase 6543→5432, direct unchanged)
- Full suite: 1774 passed, 1 skipped
- ruff clean on both files
- sse.py parses clean

## 5. Known issues

- Cannot verify the live LISTEN succeeds until deploy (the fix is DSN-shaping
  logic, validated by unit tests; runtime confirmation requires the Fly
  instance to reconnect against the real session pooler).
- The older `Application startup failed` Sentry issue (DAWN-SNOWFLAKE-1729-2,
  343 occurrences) is from prior deploy churn on the old machine and is not
  addressed here — current instance starts clean (health: database ok).

## 6. What is next

- Merge on CI green + `fly deploy`.
- After deploy: confirm DAWN-SNOWFLAKE-1729-23 stops firing (no new
  `SSE listener error` events) and `SSE: LISTEN established` appears in logs.

---

**Validation Target:** SSE listener DSN normalisation for Supabase session pooler
**Not in Scope:** main pool config, TooManyConnectionsError (already resolved), startup-failure issue
**Suggested Next Step:** WARP🔹CMD review + merge + deploy; verify Sentry issue 23 goes quiet
