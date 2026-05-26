-- 058: retire copy_targets — migrate rows to copy_trade_tasks, drop table
--
-- copy_targets was the Phase 3 table; copy_trade_tasks is the canonical table
-- since Phase 5E. All Python writers have been migrated. This migration
-- backfills any remaining copy_targets rows that are not already in
-- copy_trade_tasks, then drops the old table.

-- Backfill: copy active rows that are not already in copy_trade_tasks.
-- Uses COALESCE to handle both old schema (wallet_address) and new schema
-- (target_wallet_address) columns that may coexist after migration 009.
INSERT INTO copy_trade_tasks (user_id, wallet_address, task_name, status,
                              copy_mode, copy_amount)
SELECT
    ct.user_id,
    COALESCE(ct.target_wallet_address, ct.wallet_address) AS wallet_address,
    'imported-' || LEFT(COALESCE(ct.target_wallet_address, ct.wallet_address), 8) AS task_name,
    CASE
        WHEN ct.status = 'active' THEN 'active'
        WHEN ct.enabled = TRUE    THEN 'active'
        ELSE 'paused'
    END AS status,
    'fixed' AS copy_mode,
    5.00   AS copy_amount
FROM copy_targets ct
WHERE COALESCE(ct.target_wallet_address, ct.wallet_address) IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM copy_trade_tasks ctt
     WHERE ctt.user_id = ct.user_id
       AND ctt.wallet_address = COALESCE(ct.target_wallet_address, ct.wallet_address)
  )
ON CONFLICT DO NOTHING;

DROP TABLE IF EXISTS copy_targets;
