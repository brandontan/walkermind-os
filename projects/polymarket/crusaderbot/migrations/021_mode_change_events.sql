-- Migration 021: Track F -- mode_change_events audit table
-- Records every trading-mode transition with reason and actor.
-- Reasons: USER_CONFIRMED | AUTO_FALLBACK | OPERATOR_OVERRIDE

BEGIN;

CREATE TABLE IF NOT EXISTS mode_change_events (
    id              BIGSERIAL   PRIMARY KEY,
    user_id         UUID        REFERENCES users(id) ON DELETE SET NULL,
    from_mode       TEXT        NOT NULL,
    to_mode         TEXT        NOT NULL,
    reason          TEXT        NOT NULL,
    triggered_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mode_change_events_user
    ON mode_change_events (user_id, triggered_at DESC);

CREATE INDEX IF NOT EXISTS idx_mode_change_events_reason
    ON mode_change_events (reason, triggered_at DESC);

COMMIT;
