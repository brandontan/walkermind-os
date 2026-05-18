-- Migration 036: UI Responsive Polish
-- Adds market filter columns and auto_redeem boolean to user_settings.
-- category_filters TEXT[] and auto_redeem_mode VARCHAR already exist from migration 001.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS min_liquidity      NUMERIC(18,2) NOT NULL DEFAULT 1000,
    ADD COLUMN IF NOT EXISTS max_resolution_days INT,
    ADD COLUMN IF NOT EXISTS min_volume_24h     NUMERIC(18,2) NOT NULL DEFAULT 100,
    ADD COLUMN IF NOT EXISTS auto_redeem        BOOLEAN NOT NULL DEFAULT FALSE;

-- Rollback:
-- ALTER TABLE user_settings
--     DROP COLUMN IF EXISTS min_liquidity,
--     DROP COLUMN IF EXISTS max_resolution_days,
--     DROP COLUMN IF EXISTS min_volume_24h,
--     DROP COLUMN IF EXISTS auto_redeem;
