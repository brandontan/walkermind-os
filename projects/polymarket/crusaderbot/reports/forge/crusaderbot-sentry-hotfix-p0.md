# WARP•FORGE Report — crusaderbot-sentry-hotfix-p0

**Branch:** WARP/CRUSADERBOT-SENTRY-HOTFIX-P0
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Migration runner crash fix + job_runs serialization + schema gap fills
**Not in Scope:** New features, live trading, architecture changes
**Suggested Next Step:** WARP🔹CMD review → merge → Fly.io redeploy

---

## 1. What was built

Three targeted fixes for Sentry production blockers:

**FIX 1 — P0 startup crash (DAWN-SNOWFLAKE-1729-1K)**
Migration 032 crash: `copy_trade_events` was created in migration 009 without a `user_id` column. Migration 032 used `CREATE TABLE IF NOT EXISTS` (no-op since table exists) then tried `CREATE INDEX ON copy_trade_events (user_id)` — fails with "column user_id does not exist". Bot could not start.

Fix: Rewrote migration 032 to use `ALTER TABLE copy_trade_events ADD COLUMN IF NOT EXISTS` for each new column (`user_id`, `position_id`, `target_wallet`, `market_id`, `size_usdc`). Indexes now created on columns that actually exist.

**FIX 2 — P1 high (DAWN-SNOWFLAKE-1729-5 — 5383 events)**
`job_tracker.record_job_event` passed `metadata` (Python `dict`) as `$6` to asyncpg for a `JSONB` column. asyncpg does not auto-serialize Python dicts; it raises "expected str, got dict".

Fix: `json.dumps(metadata) if metadata is not None else None` before passing to the INSERT.

**FIX 3 — P3 schema (DAWN-SNOWFLAKE-1729-1A + DAWN-SNOWFLAKE-1729-10)**
Two schema gaps and two query bugs:
- Migration 034 added: `ALTER TABLE positions ADD COLUMN IF NOT EXISTS market_question TEXT` and `ALTER TABLE positions ADD COLUMN IF NOT EXISTS strategy_type VARCHAR(50)`. Queries that access these columns directly on positions (without JOIN) now return NULL instead of crashing.
- `share_card.py`: Removed `p.exit_price` from SELECT — column does not exist on positions (never migrated), and the fetched value was never used downstream.
- `dashboard.py`: Fixed `p.created_at` → `p.opened_at` in `_fetch_last_trade_action` CASE expression. Positions table uses `opened_at`, not `created_at`; the exception was silently caught but caused log noise.

---

## 2. Current system architecture

Migration runner (`database.run_migrations`) reads all `.sql` files in sorted order and executes them on every restart. All migrations must be idempotent. No change to this architecture.

The `job_tracker` module writes one row per scheduler job execution to `job_runs`. `metadata` is a JSONB column (added by migration 030) used by the exit_watch job to store RunResult counts.

---

## 3. Files created / modified

| Action | Path |
|--------|------|
| Modified | `projects/polymarket/crusaderbot/migrations/032_copy_trade_events.sql` |
| Created | `projects/polymarket/crusaderbot/migrations/034_positions_denorm_columns.sql` |
| Modified | `projects/polymarket/crusaderbot/domain/ops/job_tracker.py` |
| Modified | `projects/polymarket/crusaderbot/bot/handlers/share_card.py` |
| Modified | `projects/polymarket/crusaderbot/bot/handlers/dashboard.py` |
| Created | `projects/polymarket/crusaderbot/reports/forge/crusaderbot-sentry-hotfix-p0.md` |
| Modified | `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` |

---

## 4. What is working

- `python3 -m compileall projects/polymarket/crusaderbot/ -q` — clean, no output
- `ruff check projects/polymarket/crusaderbot/` — All checks passed
- Migration 032 is now idempotent: uses `ALTER TABLE ADD COLUMN IF NOT EXISTS` throughout; will not crash on a database where `copy_trade_events` already exists from migration 009
- Migration 034 adds missing `market_question` and `strategy_type` to positions safely
- `job_tracker.py` now serializes dict to JSON string before INSERT
- `share_card.py` no longer references `p.exit_price` (non-existent column)
- `dashboard.py` no longer references `p.created_at` (positions uses `opened_at`)

---

## 5. Known issues

- Migration 026 (`ALTER TABLE orders ADD COLUMN IF NOT EXISTS strategy_type VARCHAR(50)`) already exists and handles the orders table. The new migration 034 handles positions.
- `positions.market_question` and `positions.strategy_type` are nullable columns with no backfill — existing rows will show NULL. JOIN-based queries that alias `m.question AS market_question` continue to work correctly and are unaffected.
- Bot has not been tested against a live PostgreSQL instance in this cloud environment (no DB connection available). Migration SQL is syntactically correct and idempotent by design.

---

## 6. What is next

- WARP🔹CMD review → merge → Fly.io redeploy
- Apply migrations 032, 033, 034 to production DB (idempotent — safe on running DB)
- Verify Sentry issues 1K, 5, 1A, 10 close after deploy
- Backfill `positions.market_question` from `markets.question` JOIN if dashboard queries require populated values (separate lane, not blocking)
