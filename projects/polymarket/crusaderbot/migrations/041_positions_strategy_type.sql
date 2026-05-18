-- Migration 041: add strategy_type to positions (and market_question if missing).
--
-- Sentry -Z, -10: column "strategy_type" does not exist
-- Sentry -1A, -19: column "market_question" does not exist
--
-- positions table was missing these denormalised columns.
-- 034 added them idempotently but may not have applied on all instances.
-- This migration is a guaranteed catch-up; both columns are IF NOT EXISTS.
--
-- strategy_type on orders was already added by 026; this covers positions.
-- Idempotent: safe to replay on every startup.

ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS strategy_type   VARCHAR(50);

ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS market_question TEXT;
