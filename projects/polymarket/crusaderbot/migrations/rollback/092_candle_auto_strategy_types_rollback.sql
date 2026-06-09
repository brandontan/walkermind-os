-- rollback 092 — restore candle_auto users' strategy_types to the prior default
-- Lane WARP/smart-strike-paper-fixes (WARP-93 Issue 4)
--
-- NOTE: 092 collapsed candle_auto users' strategy_types to ['late_entry_v3'].
-- The exact per-row prior array is NOT recoverable from the post-state; this
-- rollback restores the documented prior default observed on candle_auto users
-- (['copy_trade','signal','value']). NOT auto-run — apply manually only if the
-- companion scheduler guard is also reverted.

UPDATE user_settings
   SET strategy_types = ARRAY['copy_trade','signal','value']::text[],
       updated_at     = NOW()
 WHERE active_preset = 'candle_auto'
   AND strategy_types IS DISTINCT FROM ARRAY['copy_trade','signal','value']::text[];
