-- 032_copy_trade_events.sql
-- Guarded: safe to re-run
-- Migration 032: copy_trade_events — audit log for mirrored copy trades
-- Fast Track B (copy-trade execution): records every position successfully
-- opened via the copy-trade monitor so callers can query what has been
-- mirrored without scanning idempotency rows.
--
-- copy_trade_events was created in 009_copy_trade.sql with columns:
--   id, copy_target_id, source_tx_hash, mirrored_order_id, created_at
-- This migration adds the monitor-audit columns idempotently via ALTER TABLE.
-- CREATE TABLE IF NOT EXISTS would be a no-op (table already exists) and
-- the subsequent CREATE INDEX on user_id would crash with
-- "column user_id does not exist" — hence ALTER TABLE approach here.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.
-- Safe to replay.

BEGIN;

ALTER TABLE copy_trade_events
    ADD COLUMN IF NOT EXISTS user_id       UUID         REFERENCES users(id) ON DELETE CASCADE;

ALTER TABLE copy_trade_events
    ADD COLUMN IF NOT EXISTS position_id   UUID         REFERENCES positions(id);

ALTER TABLE copy_trade_events
    ADD COLUMN IF NOT EXISTS target_wallet VARCHAR(100);

ALTER TABLE copy_trade_events
    ADD COLUMN IF NOT EXISTS market_id     VARCHAR(100);

ALTER TABLE copy_trade_events
    ADD COLUMN IF NOT EXISTS size_usdc     NUMERIC(18,6);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'copy_trade_events'
          AND column_name = 'user_id'
    ) THEN
        CREATE INDEX IF NOT EXISTS idx_copy_trade_events_user_id
            ON copy_trade_events (user_id);
        CREATE INDEX IF NOT EXISTS idx_copy_trade_events_market
            ON copy_trade_events (user_id, target_wallet, market_id);
    END IF;
END $$;

COMMIT;
