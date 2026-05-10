-- Migration 018: copy_trade_tasks table
-- Phase 5E: Copy Trade dashboard + wallet discovery
-- Idempotent: CREATE TABLE IF NOT EXISTS, CREATE INDEX IF NOT EXISTS

CREATE TABLE IF NOT EXISTS copy_trade_tasks (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    wallet_address    VARCHAR(42) NOT NULL,
    task_name         VARCHAR(100) NOT NULL,
    status            VARCHAR(20)  NOT NULL DEFAULT 'paused',
    copy_mode         VARCHAR(20)  NOT NULL DEFAULT 'fixed',
    copy_amount       NUMERIC(12,2) NOT NULL DEFAULT 5.00,
    copy_pct          NUMERIC(5,4),
    tp_pct            NUMERIC(5,4) NOT NULL DEFAULT 0.20,
    sl_pct            NUMERIC(5,4) NOT NULL DEFAULT 0.10,
    max_daily_spend   NUMERIC(12,2) NOT NULL DEFAULT 100.00,
    slippage_pct      NUMERIC(5,4) NOT NULL DEFAULT 0.05,
    min_trade_size    NUMERIC(12,2) NOT NULL DEFAULT 0.50,
    reverse_copy      BOOLEAN      NOT NULL DEFAULT false,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ctt_user ON copy_trade_tasks(user_id);
