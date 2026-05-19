# WARP•FORGE Report — fix-sentry-issues

**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** 4 Sentry error fixes in copy-trade monitor, job_tracker, migration 032, dashboard import
**Not in Scope:** New features, live trading, schema additions, any other Sentry issues

---

## 1. What was built

Four targeted bug fixes for active Sentry errors:

- **Fix 1** (DAWN-SNOWFLAKE-1729-1P): Removed `.isoformat()` from `date.today()` in `_get_daily_spend` and `_record_spend` in `copy_trade/monitor.py`. asyncpg expects a `date` object for a DATE column param, not a `str` — passing a string caused `DataError: str has no toordinal`.
- **Fix 2** (DAWN-SNOWFLAKE-1729-5): Added `::jsonb` explicit cast on `$6` in the `job_runs` INSERT in `job_tracker.py`. `json.dumps(metadata)` was already correct; the cast forces column-level coercion for TEXT→JSONB boundary cases.
- **Fix 3** (DAWN-SNOWFLAKE-1729-1K): Wrapped both `CREATE INDEX` statements in migration `032_copy_trade_events.sql` with a `DO $$ IF EXISTS $$` guard on the `user_id` column. Prevents crash if migration runs against a state where `ALTER TABLE ADD COLUMN IF NOT EXISTS` was a no-op (column absent). Added `-- Guarded: safe to re-run` header.
- **Fix 4** (DAWN-SNOWFLAKE-1729-12): Confirmed `preset_picker_kb` import already resolved in this branch — no Python file references it; all call sites correctly use `preset_picker`. No code change required.

---

## 2. Current system architecture

No structural changes. Pipeline is unchanged:

```
DATA -> STRATEGY -> INTELLIGENCE -> RISK -> EXECUTION -> MONITORING
```

copy-trade monitor remains PAPER ONLY. All activation guards intact.

---

## 3. Files created / modified

| Path | Change |
|------|--------|
| `projects/polymarket/crusaderbot/services/copy_trade/monitor.py` | FIX 1: `date.today().isoformat()` → `date.today()` in `_get_daily_spend` (L424) and `_record_spend` (L440) |
| `projects/polymarket/crusaderbot/domain/ops/job_tracker.py` | FIX 2: `$6` → `$6::jsonb` in INSERT VALUES (L87) |
| `projects/polymarket/crusaderbot/migrations/032_copy_trade_events.sql` | FIX 3: `CREATE INDEX` wrapped in `DO $$ IF EXISTS $$` guard; guarded header added |
| `projects/polymarket/crusaderbot/state/CHANGELOG.md` | 1 line prepended |

---

## 4. What is working

- asyncpg DATE param now receives `date` object — no more `DataError: str has no toordinal`
- `job_runs.metadata` INSERT explicitly casts JSON string to JSONB at DB boundary
- Migration 032 is idempotent and safe to re-run on any DB state (column present or absent)
- `preset_picker_kb` ImportError already resolved in codebase; no regression

---

## 5. Known issues

- Migration 032 guard uses `information_schema.columns` check — correct for PostgreSQL; no issue expected
- Fix 4 (preset_picker_kb) was a no-op in this branch; Sentry error may still appear in production until the deployment containing this branch ships

---

## 6. What is next

```
WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/fix-sentry-issues.md
Tier: STANDARD
```

- WARP🔹CMD to review and merge PR #1170
- Deploy to Fly.io to clear the 4 Sentry issues in production
