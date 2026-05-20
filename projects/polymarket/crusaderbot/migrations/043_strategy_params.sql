-- Migration 043: Add per-user strategy parameter overrides
-- Stores per-strategy param overrides keyed by strategy name.
-- Example: {"momentum": {"drop_threshold": -0.15, "min_liquidity": 8000}}
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS strategy_params JSONB DEFAULT '{}';
COMMENT ON COLUMN user_settings.strategy_params IS
  'Per-strategy param overrides keyed by strategy name. Example: {"momentum": {"drop_threshold": -0.15}}';
