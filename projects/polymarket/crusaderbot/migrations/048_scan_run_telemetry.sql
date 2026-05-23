-- Migration 048: scan_runs telemetry table
-- Additive / idempotent. Records one row per scan tick with full observability
-- breakdown: markets seen, strategies loaded, candidates emitted, risk gate
-- decisions, paper executions, and per-bucket skip/zero/rejection reasons.
-- Used by GET /admin/scan/last and GET /admin/scan/list.

CREATE TABLE IF NOT EXISTS scan_runs (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at             TIMESTAMPTZ,
    users_evaluated         INTEGER NOT NULL DEFAULT 0,
    markets_seen            INTEGER NOT NULL DEFAULT 0,
    markets_eligible        INTEGER NOT NULL DEFAULT 0,
    strategies_loaded       INTEGER NOT NULL DEFAULT 0,
    candidates_emitted      INTEGER NOT NULL DEFAULT 0,
    risk_approved           INTEGER NOT NULL DEFAULT 0,
    risk_rejected           INTEGER NOT NULL DEFAULT 0,
    paper_orders_created    INTEGER NOT NULL DEFAULT 0,
    positions_created       INTEGER NOT NULL DEFAULT 0,
    snapshots_written       INTEGER NOT NULL DEFAULT 0,
    skip_breakdown          JSONB NOT NULL DEFAULT '{}',
    zero_reason_breakdown   JSONB NOT NULL DEFAULT '{}',
    rejection_breakdown     JSONB NOT NULL DEFAULT '{}',
    mode                    VARCHAR(16) NOT NULL DEFAULT 'PAPER',
    live_trading            BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_scan_runs_started
    ON scan_runs(started_at DESC);
