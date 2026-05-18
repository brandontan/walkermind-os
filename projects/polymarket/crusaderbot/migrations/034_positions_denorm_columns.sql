-- Migration 034: add denormalised columns to positions for direct reads.
--
-- Sentry DAWN-SNOWFLAKE-1729-1A: column "market_question" does not exist
-- Sentry DAWN-SNOWFLAKE-1729-10: column "strategy_type" does not exist
--
-- Queries that access these columns directly on positions (without JOIN) fail
-- when the columns are absent.  Adding them as nullable TEXT/VARCHAR with
-- IF NOT EXISTS makes every such query safe; existing JOIN-aliased reads
-- continue to return the live markets.question value and are unaffected.
--
-- strategy_type on orders is already handled by 026_add_strategy_type_to_orders.sql.
-- This migration covers positions so the column is available there too.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS. Safe to replay on every startup.

ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS market_question TEXT;

ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS strategy_type   VARCHAR(50);
