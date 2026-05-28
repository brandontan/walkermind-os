-- 060: on-chain withdrawal columns
--
-- Adds the fields the live capital-exit path writes to. Idempotent and
-- additive only — paper mode never populates these (transfer is deferred
-- behind EXECUTION_PATH_VALIDATED). The status enum already permits
-- 'processing' / 'completed' / 'failed' (migration 057); these columns
-- record the on-chain settlement detail for each approved withdrawal.

ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS tx_hash       VARCHAR(66);
ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS onchain_error TEXT;

-- One on-chain transfer per withdrawal: a non-null tx_hash is unique so a
-- retried approval can never double-spend the hot pool.
CREATE UNIQUE INDEX IF NOT EXISTS idx_withdrawals_tx_hash
    ON withdrawals (tx_hash) WHERE tx_hash IS NOT NULL;
