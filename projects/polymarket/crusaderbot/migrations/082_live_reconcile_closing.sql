-- 082_live_reconcile_closing.sql
-- WARP-74 — LIVE reconciliation epic (Chunk A: restart-recovery for stranded
-- `positions.status='closing'` rows).
--
-- A live close in `domain/execution/live.py:close_position` atomically claims
-- the position to status='closing', submits a GTC SELL to the broker, then
-- finalizes to 'closed'. A crash BETWEEN the SELL submit and the finalize
-- strands the row in 'closing' forever — the lifecycle poller only tracks the
-- `orders` table, never a close SELL, so nothing recovers it (P0 #2).
--
-- This migration adds the two columns the closing-position reconciler needs to
-- recover such rows SAFELY (never assume a fill):
--
--   * closing_at      — the instant the 'closing' claim was taken, so the
--                       reconciler can measure staleness from the CLOSE
--                       transition rather than `opened_at` (which is the OPEN
--                       time and would mis-flag a long-lived position the moment
--                       it begins a normal close).
--   * close_order_id  — the broker order id of the close SELL, persisted
--                       immediately after submit so a crash-stranded row can be
--                       reconciled against broker truth (filled -> finalize;
--                       killed -> roll back to 'open'; otherwise -> page).
--
-- Both columns are nullable and additive: existing rows and the paper path are
-- unaffected. No backfill — pre-existing 'closing' rows (if any) reconcile via
-- the no-close_order_id "page operator" branch.

ALTER TABLE positions ADD COLUMN IF NOT EXISTS closing_at     TIMESTAMPTZ;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS close_order_id VARCHAR(200);

-- Partial index for the closing-position recovery sweep: the reconciler scans
-- only live rows currently in the 'closing' state, a tiny slice of the table.
CREATE INDEX IF NOT EXISTS idx_positions_live_closing
    ON positions (closing_at)
    WHERE mode = 'live' AND status = 'closing';
