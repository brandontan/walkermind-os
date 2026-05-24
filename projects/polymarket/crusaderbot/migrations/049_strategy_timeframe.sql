-- 049_strategy_timeframe.sql
-- Per-user selected timeframe for short-duration crypto presets.
--
-- The crypto-short presets (confluence_scalper "Crypto Scalper" and close_sweep
-- "Close Sweep") operate only on short-duration crypto markets. This column
-- stores the user's chosen candle interval used to (a) filter which crypto
-- markets the bot trades and (b) drive light per-timeframe tuning.
--
-- Values: '5m' | '15m' | NULL (NULL = no crypto-short preset / not chosen).
--
-- Additive + idempotent: ADD COLUMN IF NOT EXISTS, safe to re-run on every
-- startup. No data loss.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS selected_timeframe VARCHAR(8);

COMMENT ON COLUMN user_settings.selected_timeframe IS
  'Timeframe for crypto short-duration presets (confluence_scalper, close_sweep): 5m | 15m | NULL';
