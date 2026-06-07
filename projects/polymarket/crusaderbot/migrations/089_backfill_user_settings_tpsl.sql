-- migration 089 — backfill user_settings TP/SL to the strategy default
-- Lane WARP/honest-tpsl-controls (WARP-83 Sub-Lane E.2, Path C)
--
-- Path C semantics: TP/SL is a STRATEGY-LEVEL property — Balanced 150% / 50%
-- for everyone, regardless of risk_profile. The risk profile governs CAPITAL
-- SIZING only (capital_alloc_pct + max_position_pct), never the exit
-- thresholds. ``user_settings.tp_pct / sl_pct`` is the single source of truth
-- the strategy reads at entry (signal_scan_job._build_trade_signal).
--
-- This migration sets EVERY user_settings row to the canonical strategy default
-- (tp_pct = 1.5, sl_pct = 0.5) so the new strategy code (which now reads
-- user_settings literally) preserves the historical 150/50 behaviour for all
-- existing users. It deliberately backfills ALL rows regardless of risk_profile
-- — Conservative gets the SAME TP/SL as Balanced (it risks fewer dollars via
-- sizing, it does NOT exit faster).
--
-- DEPLOY ORDERING (load-bearing): run_migrations() executes at app boot
-- (main.lifespan: init_pool -> run_migrations -> scheduler/scan start), so this
-- backfill lands BEFORE the new _build_trade_signal code reads user_settings.
-- Net runtime behaviour is therefore preserved across the deploy.
--
-- SCOPE (hard): touches ``user_settings`` ONLY. It does NOT touch ``positions``
-- — applied_tp_pct / applied_sl_pct on existing positions (open OR settled) are
-- entry-time snapshots and are NEVER altered retroactively.
--
-- IDEMPOTENT: re-running sets the same constant values; the WHERE clause makes a
-- re-run a no-op once converged (no row matches when all rows already equal the
-- target), so the statement is safe to apply any number of times.
--
-- ROLLBACK: migrations/rollback/089_backfill_user_settings_tpsl_rollback.sql
-- (NOT auto-run — run_migrations globs migrations/*.sql at the top level only).

UPDATE user_settings
   SET tp_pct = 1.5,
       sl_pct = 0.5
 WHERE tp_pct IS DISTINCT FROM 1.5
    OR sl_pct IS DISTINCT FROM 0.5;
