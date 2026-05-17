-- Migration 035: Extend copy_trade_tasks with new workflow columns
-- Part of WARP/CRUSADERBOT-STRATEGY-RISK-COPY
-- Idempotent: ADD COLUMN IF NOT EXISTS

ALTER TABLE copy_trade_tasks
  ADD COLUMN IF NOT EXISTS nickname        VARCHAR(100),
  ADD COLUMN IF NOT EXISTS copy_direction  VARCHAR(20) NOT NULL DEFAULT 'buys_only',
  ADD COLUMN IF NOT EXISTS execution_mode  VARCHAR(20) NOT NULL DEFAULT 'auto',
  ADD COLUMN IF NOT EXISTS allow_topups    BOOLEAN     NOT NULL DEFAULT true;

COMMENT ON COLUMN copy_trade_tasks.nickname        IS 'Human-readable target label set by user';
COMMENT ON COLUMN copy_trade_tasks.copy_direction  IS 'buys_only | buys_and_sells';
COMMENT ON COLUMN copy_trade_tasks.execution_mode  IS 'auto | manual';
COMMENT ON COLUMN copy_trade_tasks.allow_topups    IS 'If false, skip additional entries on same market';
