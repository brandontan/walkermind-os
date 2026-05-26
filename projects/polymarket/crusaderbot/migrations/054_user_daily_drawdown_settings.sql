-- Migration 054: user-configurable max drawdown halt %
-- daily_loss_override already exists (migration 001).
-- This adds max_drawdown_pct so users can set a stricter drawdown halt
-- than the system 8% floor (e.g. 5% → halt earlier).
ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS max_drawdown_pct NUMERIC
        CHECK (max_drawdown_pct IS NULL OR (max_drawdown_pct > 0 AND max_drawdown_pct <= 0.08));
