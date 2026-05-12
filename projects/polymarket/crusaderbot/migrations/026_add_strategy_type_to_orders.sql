-- Migration 026: add strategy_type column to orders table.
--
-- strategy_type was present in 001_init.sql CREATE TABLE but was never
-- backfilled via ALTER TABLE for existing databases, causing
-- UndefinedColumnError in weekly_insights._fetch_weekly_stats().
-- Idempotent — safe to run on every restart.

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS strategy_type VARCHAR(50);
