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
--   * error_msg       — a paged-marker sink (mirrors `orders.error_msg`): an
--                       unresolvable stranded close (no close_order_id, or a
--                       killed partial) is stamped `[reconcile_paged] ...` and
--                       excluded from later periodic sweeps so the operator is
--                       paged once, not every cycle (alert-fatigue guard).
--
-- All three columns are nullable and additive: existing rows and the paper path
-- are unaffected. The core live-close path does NOT depend on these columns —
-- `live.close_position` claims `status='closing'` WITHOUT them and writes
-- `closing_at`/`close_order_id` only in a best-effort follow-up UPDATE (a missing
-- column logs, never breaks the close), so applying this migration after the code
-- deploys cannot brick live closes. The reconciler self-gates: it SELECTs these
-- columns and is fail-soft, so it simply no-ops until the migration lands.

ALTER TABLE positions ADD COLUMN IF NOT EXISTS closing_at     TIMESTAMPTZ;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS close_order_id VARCHAR(200);
ALTER TABLE positions ADD COLUMN IF NOT EXISTS error_msg      VARCHAR(500);

-- Partial index for the closing-position recovery sweep: the reconciler scans
-- only live rows currently in the 'closing' state, a tiny slice of the table.
CREATE INDEX IF NOT EXISTS idx_positions_live_closing
    ON positions (closing_at)
    WHERE mode = 'live' AND status = 'closing';
