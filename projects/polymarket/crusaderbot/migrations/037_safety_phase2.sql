-- Migration 037: Trading Safety Phase 2
-- Adds partial fill tracking columns to orders table.
-- Adds slippage_tolerance_pct to user_settings.

-- Orders: track partial fill amounts
ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS filled_amount    NUMERIC(18,6) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS remaining_amount NUMERIC(18,6);

-- Backfill remaining_amount for all existing orders
UPDATE orders SET remaining_amount = size_usdc WHERE remaining_amount IS NULL;

-- User settings: per-user slippage tolerance (informational warning threshold)
ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS slippage_tolerance_pct NUMERIC(5,4) DEFAULT 0.03;

-- Orders: track aggressive-limit retry attempts (0=first submit, 1=widened, 2+=cancel)
ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS slippage_retry_count INTEGER DEFAULT 0;

-- Rollback:
-- ALTER TABLE orders
--     DROP COLUMN IF EXISTS filled_amount,
--     DROP COLUMN IF EXISTS remaining_amount;
-- ALTER TABLE user_settings
--     DROP COLUMN IF EXISTS slippage_tolerance_pct;
