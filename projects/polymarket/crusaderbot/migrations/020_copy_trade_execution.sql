-- Migration 020: Fast Track B — copy trade execution tables
-- copy_trade_idempotency : per-(user, task, leader_trade) dedup anchor
-- copy_trade_daily_spend : per-(user, task, date) spend accounting for max_daily_spend cap

BEGIN;

CREATE TABLE IF NOT EXISTS copy_trade_idempotency (
    id              BIGSERIAL   PRIMARY KEY,
    user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_id         UUID        NOT NULL REFERENCES copy_trade_tasks(id) ON DELETE CASCADE,
    leader_trade_id TEXT        NOT NULL,
    processed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT copy_trade_idempotency_unique
        UNIQUE (user_id, task_id, leader_trade_id)
);

CREATE INDEX IF NOT EXISTS idx_copy_trade_idempotency_task
    ON copy_trade_idempotency (task_id, leader_trade_id);

CREATE TABLE IF NOT EXISTS copy_trade_daily_spend (
    id          BIGSERIAL   PRIMARY KEY,
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_id     UUID        NOT NULL REFERENCES copy_trade_tasks(id) ON DELETE CASCADE,
    spend_date  DATE        NOT NULL,
    spend_usdc  NUMERIC(18, 6) NOT NULL DEFAULT 0,

    CONSTRAINT copy_trade_daily_spend_unique
        UNIQUE (user_id, task_id, spend_date)
);

CREATE INDEX IF NOT EXISTS idx_copy_trade_daily_spend_task_date
    ON copy_trade_daily_spend (task_id, spend_date);

COMMIT;
