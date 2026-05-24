-- 050_strategy_assets.sql
-- Per-user crypto asset selection for short-duration crypto presets.
--
-- The crypto-short presets (confluence_scalper "Crypto Scalper" and close_sweep
-- "Close Sweep") let the user pick which crypto assets to trade (BTC/ETH/SOL/
-- BNB...). NULL / empty array means "all whitelisted assets".
--
-- Additive + idempotent: ADD COLUMN IF NOT EXISTS, safe to re-run on every
-- startup. No data loss.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS selected_assets TEXT[];

COMMENT ON COLUMN user_settings.selected_assets IS
  'Crypto asset tickers for short-duration presets (e.g. {BTC,ETH,SOL,BNB}); NULL/empty = all whitelisted assets';
