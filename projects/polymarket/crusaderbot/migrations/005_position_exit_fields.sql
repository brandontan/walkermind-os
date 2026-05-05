-- 005_position_exit_fields.sql — R12c exit watcher snapshot fields.
--
-- Adds the per-position exit-watcher contract:
--   applied_tp_pct        — TP threshold snapshot taken at entry. Immutable
--                            after INSERT (enforced by trigger). User edits to
--                            user_settings.tp_pct must NOT mutate open
--                            positions; the snapshot is the floor of truth.
--   applied_sl_pct        — SL threshold snapshot taken at entry. Same rules.
--   force_close_intent    — Telegram-set marker that the priority chain
--                            (force_close_intent > tp_hit > sl_hit > strategy)
--                            consumes on the next tick. Replaces the legacy
--                            `force_close` column (kept for one release for
--                            in-flight rows; a follow-up lane will drop it).
--   close_failure_count   — Consecutive close-attempt failures on this
--                            position. Reset on any successful close. Drives
--                            the operator alert when persistent failures cross
--                            the 2-tick threshold.
--
-- Backfill: applied_* and force_close_intent are seeded from the legacy
-- columns so any in-flight position at deploy time keeps its exit thresholds.
--
-- Triggers:
--   trg_positions_snapshot_applied — BEFORE INSERT. If the caller did not
--                            provide applied_tp_pct/applied_sl_pct, copy from
--                            tp_pct/sl_pct so the snapshot is always populated
--                            even when older code paths INSERT without the
--                            new columns.
--   trg_positions_immutable_applied — BEFORE UPDATE. Reject any UPDATE that
--                            changes applied_tp_pct/applied_sl_pct. This is
--                            the DB-level enforcement that makes the
--                            "snapshot at entry, not updatable after" contract
--                            hold even if a buggy code path later issues an
--                            UPDATE.
--
-- Idempotency: ADD COLUMN IF NOT EXISTS + DO $$ guards. Safe to re-run.

ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS applied_tp_pct NUMERIC(5,4);

ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS applied_sl_pct NUMERIC(5,4);

ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS force_close_intent BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS close_failure_count INTEGER NOT NULL DEFAULT 0;

-- Backfill applied_* from existing tp_pct/sl_pct so open positions keep their
-- thresholds when the watcher cuts over to the new columns.
UPDATE positions
   SET applied_tp_pct = tp_pct
 WHERE applied_tp_pct IS NULL AND tp_pct IS NOT NULL;

UPDATE positions
   SET applied_sl_pct = sl_pct
 WHERE applied_sl_pct IS NULL AND sl_pct IS NOT NULL;

-- Backfill force_close_intent from the legacy force_close marker. The legacy
-- column is left intact for one release so emergency flows that have not yet
-- been redeployed continue to function.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'positions'
           AND column_name = 'force_close'
    ) THEN
        UPDATE positions
           SET force_close_intent = TRUE
         WHERE force_close_intent = FALSE
           AND force_close = TRUE;
    END IF;
END $$;

-- BEFORE INSERT trigger: auto-populate applied_* from tp_pct/sl_pct when the
-- caller did not pass explicit applied_* values. This keeps existing INSERTs
-- in paper.py / live.py correct without requiring a coupled code change in
-- the same release.
CREATE OR REPLACE FUNCTION positions_snapshot_applied_tpsl()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.applied_tp_pct IS NULL THEN
        NEW.applied_tp_pct := NEW.tp_pct;
    END IF;
    IF NEW.applied_sl_pct IS NULL THEN
        NEW.applied_sl_pct := NEW.sl_pct;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
         WHERE tgname = 'trg_positions_snapshot_applied'
    ) THEN
        CREATE TRIGGER trg_positions_snapshot_applied
            BEFORE INSERT ON positions
            FOR EACH ROW
            EXECUTE FUNCTION positions_snapshot_applied_tpsl();
    END IF;
END $$;

-- BEFORE UPDATE trigger: refuse any UPDATE that modifies applied_tp_pct or
-- applied_sl_pct. This is the DB-level enforcement of the immutability
-- contract — even if a buggy code path issues UPDATE positions SET
-- applied_tp_pct = ..., the trigger raises and the transaction aborts.
CREATE OR REPLACE FUNCTION positions_reject_applied_tpsl_update()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.applied_tp_pct IS DISTINCT FROM OLD.applied_tp_pct THEN
        RAISE EXCEPTION
            'applied_tp_pct is immutable after position creation '
            '(position_id=%)', OLD.id
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.applied_sl_pct IS DISTINCT FROM OLD.applied_sl_pct THEN
        RAISE EXCEPTION
            'applied_sl_pct is immutable after position creation '
            '(position_id=%)', OLD.id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
         WHERE tgname = 'trg_positions_immutable_applied'
    ) THEN
        CREATE TRIGGER trg_positions_immutable_applied
            BEFORE UPDATE ON positions
            FOR EACH ROW
            EXECUTE FUNCTION positions_reject_applied_tpsl_update();
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_positions_force_close_intent
    ON positions(force_close_intent)
    WHERE force_close_intent = TRUE;

CREATE INDEX IF NOT EXISTS idx_positions_close_failure
    ON positions(close_failure_count)
    WHERE close_failure_count > 0;
