-- Paper-session boundary (warp/fix-live-switch-notification-isolation).
-- The ledger has no mode column — a paper row is just "not a live row"
-- (live_ledger_filter_sql). When a user switches PAPER -> LIVE the paper
-- positions/orders are archived to mode='paper_archived', but the paper
-- ledger rows stayed visible in the paper wallet feed and kept inflating
-- wallets.balance_usdc, so PAPER -> LIVE -> PAPER showed the OLD paper
-- bankroll (e.g. 904.16) and stale activity instead of a fresh practice
-- session (#1792, owner repro). This boolean lets the switch archive the
-- old paper ledger rows out of the active paper feed while retaining them
-- for audit. Additive + idempotent; default FALSE preserves every existing
-- row. Live rows are never archived (they fail the paper predicate), so the
-- live bucket / get_live_balance is unaffected.
ALTER TABLE ledger ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE;

-- Partial index: the wallet feed filters `AND NOT archived`, and the only
-- rows we ever flip are a user's paper rows at switch time.
CREATE INDEX IF NOT EXISTS idx_ledger_user_active
    ON ledger (user_id, created_at DESC)
    WHERE archived = FALSE;
