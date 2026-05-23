-- 047_deposit_confirmation_state.sql
-- Deposit confirmation-depth + reorg guard (WARP-42, audit finding H6).
--
-- Adds a confirmation state machine to `deposits`. A USDC transfer is now
-- inserted as `status='pending'` on first sighting and only credits the ledger
-- once it is DEPOSIT_CONFIRMATION_DEPTH blocks deep on the canonical chain
-- (`status='confirmed'`). A transfer whose log later arrives with removed=true
-- (orphaned by a reorg) is un-credited and marked `status='reverted'`.
--
-- Additive + idempotent: ADD COLUMN IF NOT EXISTS, safe to re-run on every
-- startup (run_migrations re-executes every file). No data loss.

ALTER TABLE deposits
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'pending';

ALTER TABLE deposits
    ADD COLUMN IF NOT EXISTS confirmed_at_block BIGINT;

-- Backfill: rows that existed before this migration were already credited by
-- the legacy immediate-credit path (they have confirmed_at set). Mark them
-- 'confirmed' so the new confirm pass never re-credits them. This matches only
-- legacy rows; genuine new-code pending rows have confirmed_at = NULL.
UPDATE deposits
   SET status = 'confirmed'
 WHERE confirmed_at IS NOT NULL
   AND status = 'pending';

-- Confirm pass scans pending deposits each tick; index keeps it cheap.
CREATE INDEX IF NOT EXISTS idx_deposits_status_pending
    ON deposits(status) WHERE status = 'pending';
