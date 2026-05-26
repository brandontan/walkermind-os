-- 053_user_max_per_trade.sql
-- Per-user "max $ per trade" control with two opt-in modes (owner-directed).
--   mode 'auto'  -> system default ($25 flat cap; existing behaviour, unchanged)
--   mode 'fixed' -> max_per_trade_usdc dollars (bounded [1, ABS_MAX] in code)
--   mode 'pct'   -> max_per_trade_pct of equity (bounded [0.5%, 10%] in code)
-- Additive + idempotent. The hard system ceilings (Kelly, 10%-of-equity position
-- fence, $500 absolute) are enforced in code and are NOT overridable here.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS max_per_trade_mode TEXT NOT NULL DEFAULT 'auto',
    ADD COLUMN IF NOT EXISTS max_per_trade_usdc NUMERIC,
    ADD COLUMN IF NOT EXISTS max_per_trade_pct  NUMERIC;

-- Guard the mode to the three known values (defensive; app also validates).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'user_settings_max_per_trade_mode_chk'
    ) THEN
        ALTER TABLE user_settings
            ADD CONSTRAINT user_settings_max_per_trade_mode_chk
            CHECK (max_per_trade_mode IN ('auto', 'fixed', 'pct'));
    END IF;
END $$;
