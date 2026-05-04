-- R10/R11/R12 hardening: explicit force-close marker, on-chain redemption tracking,
-- and Polymarket condition_id storage so we can call CTF.redeemPositions().

ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS force_close BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE markets
    ADD COLUMN IF NOT EXISTS condition_id VARCHAR(66);

-- One on-chain redemption per condition is enough; all per-user winning
-- positions in that market settle internally against the master wallet's
-- recovered USDC. This table dedupes the on-chain tx so we never
-- redeemPositions twice for the same condition.
CREATE TABLE IF NOT EXISTS live_redemptions (
    condition_id VARCHAR(66) PRIMARY KEY,
    tx_hash      VARCHAR(66),
    gas_used     BIGINT,
    redeemed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
