-- migration 092 — align candle_auto users' strategy_types to ['late_entry_v3']
-- Lane WARP/smart-strike-paper-fixes (WARP-93 Issue 4)
--
-- Context: candle_auto (Smart Strike) users route purely by active_preset through
-- the new orchestrator (signal_scan_job): active_preset 'candle_auto' ->
-- late_entry_v3 (deny-by-default). The legacy user_settings.strategy_types array
-- (e.g. ['copy_trade','signal','value']) is NOT read by that path, but the legacy
-- scheduler.run_signal_scan copy_trade scan DID iterate strategy_types — so a
-- stale 'copy_trade' entry could bleed a copy_trade scan onto a Smart Strike user.
-- The companion code change (scheduler._ORCHESTRATOR_MANAGED_PRESETS guard) now
-- skips managed-preset users in that legacy path; this migration additionally
-- makes the stored array semantically honest so the DB reflects code truth
-- (late_entry_v3 is the only strategy a candle_auto user runs).
--
-- DEPLOY ORDERING: run_migrations() executes at app boot before the scanner
-- starts, so the aligned values are in place before any scan tick.
--
-- IDEMPOTENT: the WHERE clause (IS DISTINCT FROM) makes a converged re-run a
-- no-op.
--
-- ROLLBACK: migrations/rollback/092_candle_auto_strategy_types_rollback.sql
-- (NOT auto-run — run_migrations globs migrations/*.sql at the top level only).

UPDATE user_settings
   SET strategy_types = ARRAY['late_entry_v3']::text[],
       updated_at     = NOW()
 WHERE active_preset = 'candle_auto'
   AND strategy_types IS DISTINCT FROM ARRAY['late_entry_v3']::text[];
