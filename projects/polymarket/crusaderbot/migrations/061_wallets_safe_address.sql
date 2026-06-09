-- 061: pre-computed Polymarket Safe-proxy address per user (custody migration).
--
-- Each user's deposit EOA already has a deterministic Safe proxy address
-- via CREATE2 from the Polymarket Safe factory. Storing it now (while still
-- in EOA custody mode) lets:
--   * the deposit watcher learn the Safe address ahead of any cutover,
--   * a single backfill pass populate the column without re-deriving on
--     every read,
--   * Chunk 4 cutover flip CUSTODY_MODE='safe' without a schema change.
--
-- Additive + idempotent: ADD COLUMN IF NOT EXISTS. Nullable until backfilled.

ALTER TABLE wallets ADD COLUMN IF NOT EXISTS safe_address VARCHAR(42);

-- Deposit watcher will use this index to look up the user from a Safe-address
-- transfer once Safe deposits are accepted. Partial index keeps it cheap.
CREATE UNIQUE INDEX IF NOT EXISTS idx_wallets_safe_address
    ON wallets (safe_address) WHERE safe_address IS NOT NULL;
