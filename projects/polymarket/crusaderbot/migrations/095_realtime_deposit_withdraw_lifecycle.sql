-- 095: realtime deposit/withdraw lifecycle truth (#1780)
--
-- Additive/idempotent. Formalizes the custody/accounting lifecycle used by the
-- near-realtime deposit watcher, immediate sweep trigger, and withdrawal
-- lock/submit/confirm/failure-unlock path. Existing rows are backfilled into
-- truthful lifecycle states without changing balances or live-guard flags.

ALTER TABLE deposits
    ADD COLUMN IF NOT EXISTS lifecycle_state VARCHAR(30) NOT NULL DEFAULT 'detected';

ALTER TABLE deposits
    ADD COLUMN IF NOT EXISTS sweep_tx_hash VARCHAR(66);

ALTER TABLE deposits
    ADD COLUMN IF NOT EXISTS sweep_error TEXT;

UPDATE deposits
   SET lifecycle_state = CASE
       WHEN status = 'pending' THEN 'confirming'
       WHEN status = 'reverted' THEN 'failed'
       WHEN swept = TRUE THEN 'swept'
       ELSE 'available'
   END
 WHERE lifecycle_state = 'detected';

CREATE INDEX IF NOT EXISTS idx_deposits_lifecycle_state
    ON deposits(lifecycle_state);

CREATE INDEX IF NOT EXISTS idx_deposits_confirmed_unswept
    ON deposits(user_id, lifecycle_state)
    WHERE status = 'confirmed' AND swept = FALSE;

ALTER TABLE withdrawals
    ADD COLUMN IF NOT EXISTS lifecycle_state VARCHAR(30) NOT NULL DEFAULT 'withdraw_pending';

ALTER TABLE withdrawals
    ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ;

ALTER TABLE withdrawals
    ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ;

UPDATE withdrawals
   SET lifecycle_state = CASE
       WHEN status = 'pending' THEN 'withdraw_pending'
       WHEN status = 'approved' THEN 'withdraw_pending'
       WHEN status = 'processing' THEN 'confirming'
       WHEN status = 'completed' THEN 'swept'
       WHEN status IN ('failed', 'rejected') THEN 'failed'
       ELSE lifecycle_state
   END
 WHERE lifecycle_state = 'withdraw_pending';

CREATE INDEX IF NOT EXISTS idx_withdrawals_lifecycle_state
    ON withdrawals(lifecycle_state);
