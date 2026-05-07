-- 013_copy_trade_events_nullable_fk.sql
-- Convert copy_trade_events.copy_target_id FK from ON DELETE CASCADE to
-- ON DELETE SET NULL so the append-only audit log survives target deletion
-- as orphan rows with NULL FK, instead of being cascade-deleted alongside
-- the parent copy_targets row. The column itself is already nullable
-- (no NOT NULL in 009_copy_trade.sql); this migration only changes the
-- referential action, making the FK behave as a true nullable FK.
--
-- Per-follower dedup remains intact: the UNIQUE (copy_target_id,
-- source_tx_hash) composite still guards re-mirroring of the same leader
-- trade by the same follower while the target is active.
--
-- Idempotency: guarded by an existence check on pg_constraint so safe
-- to re-run on startup.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'copy_trade_events_copy_target_id_fkey'
           AND confdeltype = 'c'  -- 'c' = CASCADE; 'n' = SET NULL
    ) THEN
        ALTER TABLE copy_trade_events
            DROP CONSTRAINT copy_trade_events_copy_target_id_fkey;

        ALTER TABLE copy_trade_events
            ADD CONSTRAINT copy_trade_events_copy_target_id_fkey
            FOREIGN KEY (copy_target_id)
            REFERENCES copy_targets(id)
            ON DELETE SET NULL;
    END IF;
END
$$;
