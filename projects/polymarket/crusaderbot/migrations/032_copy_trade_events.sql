-- Migration 032: copy_trade_events — audit log for mirrored copy trades
-- Fast Track B (copy-trade execution): records every position successfully
-- opened via the copy-trade monitor so callers can query what has been
-- mirrored without scanning idempotency rows.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.
-- Safe to replay.

BEGIN;

CREATE TABLE IF NOT EXISTS copy_trade_events (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    position_id    UUID         REFERENCES positions(id),
    target_wallet  VARCHAR(100) NOT NULL,
    market_id      VARCHAR(100) NOT NULL,
    size_usdc      NUMERIC(18,6),
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_copy_trade_events_user_id
    ON copy_trade_events (user_id);

CREATE INDEX IF NOT EXISTS idx_copy_trade_events_market
    ON copy_trade_events (user_id, target_wallet, market_id);

COMMIT;
