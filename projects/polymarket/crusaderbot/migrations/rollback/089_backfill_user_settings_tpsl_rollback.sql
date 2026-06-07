-- Rollback for migration 089 (WARP-83 E.2 user_settings TP/SL backfill).
-- NOT auto-run: run_migrations() globs migrations/*.sql at the top level only.
-- Apply manually to revert.
--
-- IMPORTANT — this rollback is a BEST-EFFORT, NON-LOSSLESS revert. Migration 089
-- overwrote any prior per-row tp_pct / sl_pct values with the strategy default
-- (1.5 / 0.5); the pre-089 values are not preserved, so a perfect restore is not
-- possible. This script restores the COLUMN DEFAULTS that were in effect before
-- the backfill (tp_pct default 0.90, sl_pct default 0.40) for every row, which
-- returns user_settings to its pre-089 schema-default state.
--
-- Only run this if the E.2 strategy-code change is ALSO reverted — otherwise the
-- strategy would read these reverted values literally (intended, but no longer
-- the signed-off 150/50 behaviour).
--
-- SCOPE: touches ``user_settings`` ONLY. Does NOT touch ``positions``.

UPDATE user_settings
   SET tp_pct = 0.90,
       sl_pct = 0.40
 WHERE tp_pct IS DISTINCT FROM 0.90
    OR sl_pct IS DISTINCT FROM 0.40;
