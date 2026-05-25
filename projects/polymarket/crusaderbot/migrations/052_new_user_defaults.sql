-- Migration 052: new user defaults — close_sweep preset, aggressive profile, bot OFF
--
-- Sets column-level defaults so every new user_settings row gets the most
-- profitable out-of-the-box config without requiring manual setup.
-- Existing users are NOT touched — only new rows inserted after this migration.
--
-- Default rationale:
--   risk_profile  = aggressive  → min_liquidity 10k, max_concurrent 20
--   active_preset = close_sweep → late_entry_v3 candle strategy
--   capital_alloc = 0.40        → 40% per trade (close_sweep default)
--   tp_pct        = 0.90        → +90% take-profit
--   sl_pct        = 0.40        → -40% stop-loss
--   auto_trade_on stays FALSE   → user must explicitly enable (users table default)

ALTER TABLE user_settings
    ALTER COLUMN risk_profile    SET DEFAULT 'aggressive',
    ALTER COLUMN active_preset   SET DEFAULT 'close_sweep',
    ALTER COLUMN capital_alloc_pct SET DEFAULT 0.40,
    ALTER COLUMN tp_pct          SET DEFAULT 0.90,
    ALTER COLUMN sl_pct          SET DEFAULT 0.40;
