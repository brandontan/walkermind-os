# WARP•R00T Report — live-enable-mode-truncation

Last Updated : 2026-06-12 22:10
Project      : CrusaderBot
Project Root : projects/polymarket/crusaderbot
Branch       : warp/root-live-enable-mode-truncation
Tier         : MAJOR
Claim Level  : NARROW INTEGRATION
Source       : Sentry (vurtnex/dawn-snowflake-1729) issues DAWN-SNOWFLAKE-1729-33 / -34

## Problem found
`/api/web/live/enable` was throwing `StringDataRightTruncationError: value too long for type character varying(10)` in production (env=production, crusaderbot.fly.dev), 2 events on 2026-06-12. The self-serve PAPER -> LIVE switch was fully broken: the error aborted the whole transaction so no user could move to LIVE.

## Root cause
`domain/activation/live_mode.enable_live_self_serve` archives a user's paper simulation rows by setting `positions.mode` and `orders.mode` to `PAPER_ARCHIVED_MODE = 'paper_archived'` (14 chars). Both columns are declared `VARCHAR(10)` in `migrations/001_init.sql` (lines 116, 137). 14 > 10 → Postgres raised `StringDataRightTruncationError` at the `UPDATE positions` statement (`live_mode.py:194`), inside the switch's single `c.transaction()` — so the entire enable rolled back (atomic; no partial/corrupt state, but the feature never completed). Introduced by the self-serve-paper-to-live-switch lane (#1782 / PR #1784).

## Risk level
MAJOR — capital/live-path. No data corruption (atomic rollback), but a user-facing LIVE activation path was 100% broken in production.

## Technical impact
Every `POST /api/web/live/enable` (and the Telegram typed-confirm trading-mode switch, which calls the same helper) returned HTTP 500 and left the user in PAPER. The $5 / checklist Auto-Trade gate downstream was never reached because the mode switch itself failed first.

## Recommended solution (implemented)
Widen the column, not the sentinel — root-cause fix that preserves the descriptive archived value and the carefully-built archive logic:
- New `migrations/097_widen_positions_orders_mode.sql`: `ALTER TABLE positions ALTER COLUMN mode TYPE VARCHAR(20)` + same for `orders`, each guarded on `character_maximum_length < 20` so the migration is idempotent. Increasing a varchar length limit is a catalog-only change in Postgres (no table rewrite; brief lock only). Auto-applies on next deploy via the tracked `run_migrations()` runner.
- No code change to `enable_live_self_serve` — once the column is wide enough, the already-deployed code succeeds.

## Files affected
- projects/polymarket/crusaderbot/migrations/097_widen_positions_orders_mode.sql (new)
- projects/polymarket/crusaderbot/tests/test_live_enable_mode_width.py (new — pins sentinel width + migration widening)
- state/PROJECT_STATE.md, state/CHANGELOG.md (repo-truth sync)

## Validation performed
- Targeted pytest: test_live_enable_mode_width.py + test_self_serve_live_mode.py → 10 passed.
- Migration SQL: no BOM, balanced `DO $$ ... END $$;`, idempotency guard present.
- ruff clean on new test.
- Full suite re-run green (see CHANGELOG).

## Inviolable invariants — confirmed clean
DDL is a pure varchar widening on `positions.mode` / `orders.mode`; no risk-constant / Kelly change; no live-guard flip (`USE_REAL_CLOB` / `EXECUTION_PATH_VALIDATED` / `ENABLE_LIVE_TRADING` / `CAPITAL_MODE_CONFIRMED`); no secrets; no real fund movement; asyncio only.

## What is next
After merge + deploy, confirm `/api/web/live/enable` returns 200 and the Sentry issue stops recurring. The other live `mode` values ('paper', 'live') are unaffected.
