-- Migration 001: Settlement domain tables
-- Priority 7 -- Settlement, Retry, and Reconciliation (sections 43-48)
-- Branch: WARP/settlement-ddl-migration
-- Date: 2026-04-27
--
-- These tables are also auto-created idempotently by DatabaseClient._apply_schema()
-- on every connect. This file exists for production deployment auditing and
-- migration tooling that requires explicit SQL files.
--
-- Safe to run multiple times (CREATE TABLE IF NOT EXISTS).

-- Settlement lifecycle event log (append-only, indexed by workflow)
CREATE TABLE IF NOT EXISTS settlement_events (
    event_id        TEXT        PRIMARY KEY,
    event_type      TEXT        NOT NULL,
    workflow_id     TEXT        NOT NULL,
    settlement_id   TEXT,
    payload         JSONB       NOT NULL DEFAULT '{}',
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_settlement_events_workflow
    ON settlement_events (workflow_id, occurred_at ASC);

-- Per-attempt retry history (composite PK: workflow_id + attempt_number)
CREATE TABLE IF NOT EXISTS settlement_retry_history (
    workflow_id         TEXT        NOT NULL,
    attempt_number      INTEGER     NOT NULL,
    outcome             TEXT        NOT NULL,
    settlement_id       TEXT,
    blocked_reason      TEXT,
    delay_before_next_s DOUBLE PRECISION,
    attempted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trace_refs          JSONB       NOT NULL DEFAULT '{}',
    PRIMARY KEY (workflow_id, attempt_number)
);

-- Latest reconciliation result per workflow (upsert on workflow_id)
CREATE TABLE IF NOT EXISTS settlement_reconciliation_results (
    workflow_id         TEXT        PRIMARY KEY,
    settlement_id       TEXT,
    outcome             TEXT        NOT NULL,
    mismatch_reason     TEXT,
    repair_action       TEXT        NOT NULL,
    is_stuck            BOOLEAN     NOT NULL DEFAULT FALSE,
    internal_status     TEXT        NOT NULL,
    external_status     TEXT,
    trace_refs          JSONB       NOT NULL DEFAULT '{}'
);
