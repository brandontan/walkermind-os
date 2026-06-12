-- 099: deposit asset/network audit truth for multi-asset deposit selector (#1793)
--
-- Additive/idempotent. Existing credited deposits are backfilled as Polygon
-- USDC.e because that is the only token/network the historical watcher credited.
-- New watcher rows preserve original token/network/contract + normalized USD
-- credit amount separately from amount_usdc.

ALTER TABLE deposits
    ADD COLUMN IF NOT EXISTS token_symbol VARCHAR(20) NOT NULL DEFAULT 'USDC.e';

ALTER TABLE deposits
    ADD COLUMN IF NOT EXISTS token_address VARCHAR(66);

ALTER TABLE deposits
    ADD COLUMN IF NOT EXISTS network VARCHAR(40) NOT NULL DEFAULT 'Polygon';

ALTER TABLE deposits
    ADD COLUMN IF NOT EXISTS chain_id INTEGER NOT NULL DEFAULT 137;

ALTER TABLE deposits
    ADD COLUMN IF NOT EXISTS token_decimals INTEGER NOT NULL DEFAULT 6;

ALTER TABLE deposits
    ADD COLUMN IF NOT EXISTS normalized_amount_usdc NUMERIC(18,6);

UPDATE deposits
   SET normalized_amount_usdc = amount_usdc
 WHERE normalized_amount_usdc IS NULL;

CREATE INDEX IF NOT EXISTS idx_deposits_asset_network
    ON deposits(token_symbol, network, chain_id);
