-- Migration 002: Capital mode confirmation receipts
-- Priority 8-E -- Capital Mode Confirmation Flow (CAPITAL_MODE_CONFIRMED gate)
-- Branch: WARP/capital-mode-confirm
-- Date: 2026-04-30
--
-- Adds the runtime acknowledgment receipt that complements the env-var gate
-- CAPITAL_MODE_CONFIRMED. The LiveExecutionGuard requires BOTH the env var
-- AND an unrevoked confirmation row in this table before allowing live capital
-- execution.  This is the second layer of the capital-mode defence-in-depth.
--
-- Auto-created idempotently by DatabaseClient._apply_schema() on every connect.
-- This file exists for production deployment auditing and migration tooling
-- that requires explicit SQL files.
--
-- Safe to run multiple times (CREATE TABLE IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS capital_mode_confirmations (
    confirmation_id         TEXT        PRIMARY KEY,
    operator_id             TEXT        NOT NULL,
    mode                    TEXT        NOT NULL,
    acknowledgment_token    TEXT        NOT NULL,
    upstream_gates_snapshot JSONB       NOT NULL DEFAULT '{}',
    confirmed_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at              TIMESTAMPTZ,
    revoked_by              TEXT,
    revoke_reason           TEXT
);

-- Latest-unrevoked lookup: guard checks the most recent active confirmation
-- per mode.  Partial index keeps the hot path narrow.
CREATE INDEX IF NOT EXISTS idx_capital_mode_confirmations_active
    ON capital_mode_confirmations (mode, confirmed_at DESC)
    WHERE revoked_at IS NULL;

-- Operator audit lookup: list every confirmation/revoke event for a given operator.
CREATE INDEX IF NOT EXISTS idx_capital_mode_confirmations_operator
    ON capital_mode_confirmations (operator_id, confirmed_at DESC);
