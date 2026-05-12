# WARP•FORGE Report — fix-migration-idempotency

**Branch:** WARP/fix-migration-idempotency
**Date:** 2026-05-12
**Tier:** MAJOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** run_migrations() startup path + signal_feeds seed statements in migrations 024 and 025
**Not in Scope:** schema changes, new columns, execution/risk path, other migration content
**Suggested Next Step:** WARP•SENTINEL validation required before merge

---

## 1. What Was Built

Fixed the migration idempotency crash loop that caused `UniqueViolationError` on every container restart (Sentry: DAWN-SNOWFLAKE-1729-2, DAWN-SNOWFLAKE-1729-3, 122 events over 4 days).

**Root cause:** `signal_feeds` has `slug VARCHAR(60) NOT NULL UNIQUE`. Migrations 024 and 025 INSERT into `signal_feeds` using `ON CONFLICT (id) DO NOTHING`. If the slug row already exists with a different UUID (e.g. from a prior schema migration or dev run), the `id` conflict guard does NOT fire — the `slug` uniqueness constraint fires instead, raising an unhandled `UniqueViolationError`. This exception propagated through `run_migrations()` with no error handling, crashing the lifespan at `Application startup failed. Exiting.` — creating the crash loop.

**Two changes applied:**

1. **migrations/024 and 025:** Changed `ON CONFLICT (id) DO NOTHING` → `ON CONFLICT DO NOTHING`. The target-less form catches ANY unique constraint violation (primary key OR slug), making the INSERT safe regardless of which UUID the slug row was originally created with.

2. **database.py `run_migrations()`:** Added per-file try/except that logs `migration failed: <filename>` with `exc_info=True` before re-raising, and an outer try/except that logs `run_migrations failed` before re-raising. The raise is preserved — migrations must not silently pass on failure; the app should abort with a visible error rather than start in an inconsistent schema state.

---

## 2. Current System Architecture

Migration runner pattern (unchanged):
- `run_migrations()` in `database.py` runs at lifespan startup after `init_pool()`
- Reads all `*.sql` files from `migrations/` sorted by filename prefix
- Executes each file in a single acquired connection
- All SQL must be idempotent: `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ADD COLUMN IF NOT EXISTS`, `INSERT ... ON CONFLICT DO NOTHING` or `WHERE NOT EXISTS`

`signal_feeds` unique constraints:
- `id UUID PRIMARY KEY` (auto-generated default)
- `slug VARCHAR(60) NOT NULL UNIQUE` ← the constraint that triggered the crash

---

## 3. Files Created / Modified

| Action | Path |
|---|---|
| Modified | `projects/polymarket/crusaderbot/migrations/024_signal_scan_engine_seed.sql` |
| Modified | `projects/polymarket/crusaderbot/migrations/025_heisenberg_live_feed.sql` |
| Modified | `projects/polymarket/crusaderbot/database.py` |
| Created  | `projects/polymarket/crusaderbot/reports/forge/fix-migration-idempotency.md` |

---

## 4. What Is Working

- `run_migrations()` now logs the exact failing migration file name + exception before re-raising — operators can immediately identify which file caused startup failure.
- Migrations 024 and 025 are now fully idempotent: `ON CONFLICT DO NOTHING` catches both `id` and `slug` uniqueness violations, so re-running on a DB that already has `crusaderbot-demo` or `crusaderbot-live` rows is a no-op.
- All other migration INSERT statements were audited and confirmed already idempotent (`WHERE NOT EXISTS` or `ON CONFLICT (col) DO NOTHING` on their respective primary keys where no secondary unique constraint conflicts exist).

---

## 5. Known Issues

- `run_migrations()` re-runs all migration files on every startup (no applied-migration tracking table). This is safe as long as all SQL is idempotent, but adds startup latency proportional to migration count. Migration tracking is a separate task — deferred.
- If a migration contains a `BEGIN`/`COMMIT` block and the connection already has an open transaction, asyncpg will raise a `NestedTransactionError`. All current migration files that use transactions (`BEGIN`/`COMMIT`) are already wrapped at file level, not statement level. No change needed here.

---

## 6. What Is Next

WARP•SENTINEL validation required for `fix-migration-idempotency` before merge.
Source: `projects/polymarket/crusaderbot/reports/forge/fix-migration-idempotency.md`
Tier: MAJOR
