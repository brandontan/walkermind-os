-- ============================================================================
-- Cleanup: flip_hunter sub-cent Gamma-fallback bug
-- ============================================================================
-- Date    : 2026-05-28
-- Branch  : WARP/ROOT-flip-hunter-stale-price-fix
-- Author  : WARP•R00T (Bayue Walker)
-- Scope   : ONE-SHOT cleanup of positions opened with sub-cent Gamma
--           outcomePrices seed values (0.505, 0.515) by `late_entry_v3` /
--           `flip_hunter` between 2026-05-28 08:55 UTC and 2026-05-28 15:05 UTC.
--           Code fix is in the same PR (`get_live_market_price` now rejects
--           sub-cent fallback; `_process_candidate` adds belt-and-suspenders
--           guard) so the bug cannot re-occur.
--
-- Impact at audit time (run preview queries first to re-confirm before COMMIT):
--   User A (7e6fbd20-0c7c-4f1c-bfc8-a07a396ef2ba): 51 positions, all closed,
--          +$17.32 fake realised P&L → wallet must be debited $17.32
--   User B (c8db805c-29b6-490c-ae52-5c0d976d4480): 32 positions (29 closed +
--          3 still open holding $10.10), +$12.84 fake realised P&L on closes →
--          wallet must be debited $12.84 AND the 3 open positions must be
--          voided at entry price (no P&L) with their $10.10 refunded.
--
-- Total expected wallet net change:
--   User A: -$17.32 (no open positions)
--   User B: -$12.84 + $10.10 = -$2.74 (closed adjustment + open refund)
--
-- Safety:
--   * Single transaction. ROLLBACK aborts everything if any assertion fails.
--   * Affects PAPER positions only (mode='paper') — no real capital touched.
--   * Adds an `adjustment` ledger entry per user explaining the reversal.
--   * Marks the still-open positions with exit_reason='cleanup_void' so they
--     are auditable as bot-driven cleanup rather than user-driven exits.
--   * audit_log row records the operation.
--
-- ============================================================================

-- ── PREVIEW (run alone; no writes) ─────────────────────────────────────────
-- Re-confirm the scope before committing. Numbers should match the comment
-- block above. If they differ, STOP and re-investigate.
SELECT
  'closed_to_reverse' AS section,
  user_id::text AS user_id,
  COUNT(*) AS n,
  SUM(pnl_usdc)::numeric(12,4) AS sum_pnl
FROM positions
WHERE strategy_type = 'late_entry_v3'
  AND active_preset = 'flip_hunter'
  AND entry_price IN (0.505, 0.515)
  AND status = 'closed'
  AND mode = 'paper'
GROUP BY user_id
UNION ALL
SELECT
  'open_to_void' AS section,
  user_id::text AS user_id,
  COUNT(*) AS n,
  SUM(size_usdc)::numeric(12,4) AS sum_size
FROM positions
WHERE strategy_type = 'late_entry_v3'
  AND active_preset = 'flip_hunter'
  AND entry_price IN (0.505, 0.515)
  AND status IN ('open', 'pending_settlement')
  AND mode = 'paper'
GROUP BY user_id
ORDER BY section, user_id;


-- ── CLEANUP (run inside BEGIN / COMMIT) ────────────────────────────────────
BEGIN;

-- Step 1 — Reverse realised P&L on CLOSED affected positions.
-- Inserts one ledger row per affected user with the negative of their fake
-- realised P&L sum, and debits the wallet by the same amount.
WITH per_user AS (
  SELECT user_id, SUM(pnl_usdc) AS fake_pnl
  FROM positions
  WHERE strategy_type = 'late_entry_v3'
    AND active_preset = 'flip_hunter'
    AND entry_price IN (0.505, 0.515)
    AND status = 'closed'
    AND mode = 'paper'
  GROUP BY user_id
)
INSERT INTO ledger (user_id, type, amount_usdc, note)
SELECT
  user_id,
  'adjustment',
  -fake_pnl,
  'cleanup 2026-05-28: reverse fake P&L from flip_hunter sub-cent Gamma '
  || 'fallback (entry @0.505/0.515 = synthetic seed prices, not real CLOB '
  || 'activity); net realised P&L on affected closed positions = $'
  || fake_pnl::text
FROM per_user;

UPDATE wallets w
SET balance_usdc = w.balance_usdc - sub.fake_pnl
FROM (
  SELECT user_id, SUM(pnl_usdc) AS fake_pnl
  FROM positions
  WHERE strategy_type = 'late_entry_v3'
    AND active_preset = 'flip_hunter'
    AND entry_price IN (0.505, 0.515)
    AND status = 'closed'
    AND mode = 'paper'
  GROUP BY user_id
) sub
WHERE w.user_id = sub.user_id;

-- Step 2 — Void STILL-OPEN affected positions at entry price (zero P&L).
-- Updates positions → closed/cleanup_void, current_price=entry_price, pnl=0.
UPDATE positions
SET status = 'closed',
    closed_at = NOW(),
    current_price = entry_price,
    pnl_usdc = 0,
    exit_reason = 'cleanup_void'
WHERE strategy_type = 'late_entry_v3'
  AND active_preset = 'flip_hunter'
  AND entry_price IN (0.505, 0.515)
  AND status IN ('open', 'pending_settlement')
  AND mode = 'paper';

-- Step 3 — Refund the size_usdc that was debited on open for each voided row.
-- One ledger trade_close per voided position (mirrors paper.execute close
-- ledger convention so reports stay parseable).
INSERT INTO ledger (user_id, type, amount_usdc, ref_id, note)
SELECT
  p.user_id,
  'trade_close',
  p.size_usdc,
  p.id,
  'cleanup 2026-05-28: refund size on voided flip_hunter sub-cent position '
  || '(' || p.market_id || ')'
FROM positions p
WHERE p.strategy_type = 'late_entry_v3'
  AND p.active_preset = 'flip_hunter'
  AND p.entry_price IN (0.505, 0.515)
  AND p.mode = 'paper'
  AND p.exit_reason = 'cleanup_void';

UPDATE wallets w
SET balance_usdc = w.balance_usdc + sub.refund
FROM (
  SELECT user_id, SUM(size_usdc) AS refund
  FROM positions
  WHERE strategy_type = 'late_entry_v3'
    AND active_preset = 'flip_hunter'
    AND entry_price IN (0.505, 0.515)
    AND mode = 'paper'
    AND exit_reason = 'cleanup_void'
  GROUP BY user_id
) sub
WHERE w.user_id = sub.user_id;

-- Step 4 — Audit-log entry so the cleanup is traceable.
INSERT INTO audit_log (event, reason, triggered_by, created_at)
VALUES (
  'flip_hunter_sub_cent_cleanup',
  'reverse fake P&L + void open positions caused by Gamma outcomePrices '
  || 'sub-cent fallback in get_live_market_price; code fix shipped in '
  || 'WARP/ROOT-flip-hunter-stale-price-fix',
  'WARP•R00T (Bayue Walker)',
  NOW()
);

-- ── ASSERTIONS — fail-closed if scope expanded between preview and commit ──
DO $$
DECLARE
  remaining_open INT;
BEGIN
  SELECT COUNT(*) INTO remaining_open
  FROM positions
  WHERE strategy_type = 'late_entry_v3'
    AND active_preset = 'flip_hunter'
    AND entry_price IN (0.505, 0.515)
    AND status IN ('open', 'pending_settlement')
    AND mode = 'paper';
  IF remaining_open > 0 THEN
    RAISE EXCEPTION 'cleanup did not void all affected open positions: % remain',
      remaining_open;
  END IF;
END $$;

-- COMMIT;   -- ← uncomment when ready to apply; until then the txn ROLLBACKs
ROLLBACK;
