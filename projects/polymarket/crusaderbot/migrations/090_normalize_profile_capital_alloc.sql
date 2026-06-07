-- migration 090 — normalize non-custom risk profiles' capital_alloc_pct
-- Lane WARP/root-risk-profile-capital (WARP-83 follow-up, owner directive 2026-06-08)
--
-- Context: capital_alloc_pct (the risk-profile CAP%) now ACTUALLY drives trade
-- sizing + the total-deployment gate (conservative 0.20 / balanced 0.40 /
-- aggressive 0.60). Previously the value was written but never consumed by the
-- candle sizing path (it read user_strategies.weight instead), and
-- activate_preset force-wrote the preset's own capital_alloc_pct (e.g. 0.30) plus
-- risk_profile='balanced' on every preset toggle. The result: stored
-- capital_alloc_pct drifted away from the displayed profile (rows seen at 0.50 /
-- 0.30 / 0.20 while risk_profile='balanced').
--
-- This migration re-aligns each NON-CUSTOM profile's capital_alloc_pct to its
-- canonical per-profile default so the stored value matches the profile the user
-- sees and the sizing/deployment cap behaves as advertised. 'custom' rows are
-- LEFT UNTOUCHED — their capital_alloc_pct is user-owned (advanced override).
--
-- DEPLOY ORDERING: run_migrations() executes at app boot before the scanner
-- starts, so the normalized values are in place before the new sizing code reads
-- them.
--
-- IDEMPOTENT: the WHERE clause makes a converged re-run a no-op.
--
-- ROLLBACK: migrations/rollback/090_normalize_profile_capital_alloc_rollback.sql
-- (NOT auto-run — run_migrations globs migrations/*.sql at the top level only).

UPDATE user_settings
   SET capital_alloc_pct = 0.20
 WHERE risk_profile = 'conservative'
   AND capital_alloc_pct IS DISTINCT FROM 0.20;

UPDATE user_settings
   SET capital_alloc_pct = 0.40
 WHERE risk_profile = 'balanced'
   AND capital_alloc_pct IS DISTINCT FROM 0.40;

UPDATE user_settings
   SET capital_alloc_pct = 0.60
 WHERE risk_profile = 'aggressive'
   AND capital_alloc_pct IS DISTINCT FROM 0.60;
