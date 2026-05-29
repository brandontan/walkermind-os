-- migration 068 — narrow operator strategy roster to actually-reachable strategies
--
-- Lane: WARP/R00T/strategy-system-cleanup (MAJOR — admin surface)
--
-- Background: migration 067 seeded the `strategies` table with 12 rows, but
-- 9 of those (momentum_reversal, confluence_scalper, trend_breakout, momentum,
-- value_investor, expiration_timing, pair_arb, ensemble, whale_tracking) had
-- no user-facing preset path — every admin toggle for them was cosmetic.
--
-- WARP•R00T cleanup keeps only the 3 strategies that real users can actually
-- trigger today:
--   * late_entry_v3   — backs close_sweep / safe_close / flip_hunter presets
--   * signal_following — auto-enrolled per user (signal_publications feed)
--   * copy_trade       — separate copy_trade_tasks pipeline
--
-- The 9 cosmetic rows are deleted here. The companion code change removes the
-- strategies themselves (lib/strategies/* + domain/strategy/strategies/
-- confluence_scalper.py + momentum_reversal.py) so there is nothing to gate.
--
-- FAIL-SAFE preserved: signal_scan_job._refresh_disabled_strategies() treats
-- a missing row as enabled=TRUE, so a future re-introduction of any deleted
-- strategy comes back ON by default until the operator explicitly toggles it.

DELETE FROM strategies
 WHERE name NOT IN ('signal_following', 'late_entry_v3', 'copy_trade');
