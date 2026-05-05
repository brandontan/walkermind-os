-- 006_redeem_queue.sql — R12e auto-redeem queue.
--
-- Adds the persistent queue that the auto-redeem workers drain. The queue is
-- the single source of truth for pending and in-flight redeems so that a
-- crashed instant worker is recovered transparently by the hourly batch.
--
-- Schema:
--   id                    UUID PK
--   user_id               FK users — owner of the position being redeemed
--   position_id           FK positions — UNIQUE so re-detection cannot
--                         double-enqueue a position already pending
--   market_condition_id   condition_id from markets at enqueue time. Stored
--                         denormalised so workers do not have to re-resolve
--                         the FK if the market row mutates between enqueue
--                         and submit.
--   outcome_index         winning outcome index (0 = YES, 1 = NO) recorded at
--                         enqueue time so the worker submits the correct
--                         redeem call even if Polymarket later toggles the
--                         market state for any reason.
--   status                pending | processing | done | failed.
--                         pending  = ready for either worker
--                         processing = a worker holds the claim
--                         done     = settled (terminal)
--                         failed   = abandoned after operator escalation
--   failure_count         consecutive failures observed by the hourly worker.
--                         Operator alert fires at >= 2 (R12e spec).
--   last_error            short error fragment from the most recent failure
--                         (for forensic readability without dumping the full
--                         stack into the row).
--   queued_at             enqueue wallclock.
--   processed_at          terminal-state wallclock (done|failed).
--
-- Idempotency: CREATE TABLE IF NOT EXISTS + ADD COLUMN IF NOT EXISTS guards
-- so the migration is safe to re-run on staging redeploys.

CREATE TABLE IF NOT EXISTS redeem_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    position_id UUID NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    market_condition_id VARCHAR(80),
    outcome_index SMALLINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    failure_count SMALLINT NOT NULL DEFAULT 0,
    last_error TEXT,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at TIMESTAMPTZ,
    processed_at TIMESTAMPTZ
);

-- Defensive ADD COLUMN for staging DBs that ran an earlier draft of this
-- migration before claimed_at was added.
ALTER TABLE redeem_queue
    ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;

-- One row per position. Re-detection of a still-resolved market must not
-- double-enqueue. The unique index also lets the router use ON CONFLICT
-- DO NOTHING for atomic enqueue without a SELECT-then-INSERT race.
CREATE UNIQUE INDEX IF NOT EXISTS uq_redeem_queue_position
    ON redeem_queue(position_id);

-- Workers always pull pending rows ordered by queued_at; this partial index
-- keeps the scan cheap once done/failed rows accumulate.
CREATE INDEX IF NOT EXISTS idx_redeem_queue_pending
    ON redeem_queue(queued_at)
    WHERE status = 'pending';

-- Operator alert path inspects rows with elevated failure counts.
CREATE INDEX IF NOT EXISTS idx_redeem_queue_failed
    ON redeem_queue(failure_count)
    WHERE failure_count > 0;

-- Stale-processing reaper inspects processing rows by claimed_at age.
-- A worker crash between claim and terminal-state transition leaves the
-- row in 'processing'; the hourly worker reaps stale rows back to
-- 'pending' so they don't get stranded.
CREATE INDEX IF NOT EXISTS idx_redeem_queue_processing
    ON redeem_queue(claimed_at)
    WHERE status = 'processing';

-- Defensive: ensure the user_settings.auto_redeem_mode column exists on
-- pre-006 databases. 001_init.sql already declares it, so this is a no-op
-- on a clean install but lets a stale staging DB pick up the setting before
-- the Settings handler tries to read it.
ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS auto_redeem_mode VARCHAR(10) NOT NULL DEFAULT 'hourly';
