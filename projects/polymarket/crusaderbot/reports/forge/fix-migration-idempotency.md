# WARP•FORGE — Fix Migration Idempotency

Branch: `WARP/fix-migration-idempotency`
Tier: MAJOR
Claim Level: NARROW INTEGRATION
Date: 2026-05-12 23:30 Asia/Jakarta

---

## 1. What was built

Fixed `UniqueViolationError` on startup (Sentry DAWN-SNOWFLAKE-1729-2 & -3, 122 events).

Root cause: `signal_feeds` seed INSERTs in migrations 024 and 025 used `ON CONFLICT (id) DO NOTHING`,
which only guards the primary key column. The `slug` column carries a separate UNIQUE constraint
(`signal_feeds_slug_key`). On restart with an existing DB, the fixed UUID differed from the stored
row's UUID in some envs, so the `id` conflict did not fire — but the `slug` conflict did, aborting startup.

Fix: changed `ON CONFLICT (id) DO NOTHING` → `ON CONFLICT DO NOTHING` on the two affected INSERTs.
The broader form suppresses all unique constraint violations on the statement, making both restarts
and fresh boots idempotent regardless of which column triggers.

Secondary: added structured try/except error handling to `run_migrations()` so migration failures
log the specific filename (inner except) and propagate to the lifespan caller (outer except) with
full exc_info for Sentry capture.

## 2. Current system architecture

Migration runner contract (unchanged except error handling):

```
projects/polymarket/crusaderbot/database.py
  run_migrations()
    -> sorted(migrations/*.sql) lex order
    -> outer try: pool.acquire() context
    -> inner try per file: conn.execute(sql)
    -> inner except: log filename + exc, re-raise
    -> outer except: log context + exc, re-raise
    -> lifespan receives exception -> startup abort
```

signal_feeds idempotency after fix:

| Scenario | Behavior |
|---|---|
| Fresh DB | INSERT succeeds, slug created |
| Restart — same UUID | ON CONFLICT DO NOTHING → no-op |
| Restart — different UUID, same slug | ON CONFLICT DO NOTHING → no-op (was crashing) |
| Hard non-conflict error | Log + re-raise + startup abort |

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/migrations/024_signal_scan_engine_seed.sql` — line 24: ON CONFLICT target removed
- `projects/polymarket/crusaderbot/migrations/025_heisenberg_live_feed.sql` — line 25: ON CONFLICT target removed
- `projects/polymarket/crusaderbot/database.py` — run_migrations() lines 116–129: try/except error handling added

Created:
- `projects/polymarket/crusaderbot/reports/forge/fix-migration-idempotency.md` (this report)
- `projects/polymarket/crusaderbot/reports/sentinel/fix-migration-idempotency.md`

Modified (state sync):
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- `ON CONFLICT DO NOTHING` without a conflict target is valid PostgreSQL syntax and suppresses
  all unique constraint violations on the INSERT statement — confirmed against PostgreSQL docs.
- Migration 024 other INSERTs (markets, signal_publications, user_strategies, user_signal_subscriptions)
  are unaffected; their idempotency guards (ON CONFLICT (id), ON CONFLICT DO NOTHING, WHERE NOT EXISTS)
  were already correct.
- `run_migrations()` outer/inner try structure preserves asyncpg connection lifecycle — context manager
  exit on exception is clean; no dangling connections.
- No schema changes. No execution/risk path touched. No activation guards modified.

## 5. Known issues

- Double-logging on failure: inner except logs filename, outer except logs context — two Sentry events
  per migration crash. Noisy but informational. Non-blocking.
- CHANGELOG entry written before lane close (process deviation, pre-authorized by WARP🔹CMD).
  Post-merge: amend entry to remove "PR open awaiting WARP•SENTINEL", update timestamp to actual merge time.

## 6. What is next

- WARP•SENTINEL validation required — Tier: MAJOR.
- After APPROVED: WARP🔹CMD merge PR #1003.
- Post-merge: monitor Sentry DAWN-SNOWFLAKE-1729-2 and -3 — both must stop firing after deploy.

---

## Metadata

- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Validation Target: run_migrations() startup path; signal_feeds seed INSERTs in migrations 024 and 025
- Not in Scope: schema changes; other migration SQL; execution/risk path; activation guards
- Suggested Next Step: WARP•SENTINEL validation → WARP🔹CMD merge decision
