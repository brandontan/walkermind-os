-- 094: pre-resolved Polymarket deposit wallet per user (per-user execution Step 2).
--
-- Step 1 (#1731) shipped integrations/clob/user_client.resolve_deposit_wallet_creds
-- — given a user's HD private key, the polymarket SDK's AsyncSecureClient runs an
-- on-chain factory check to pick the deterministic deposit wallet (beacon vs
-- UUPS). That resolution is what the per-user CLOB client will sign against.
--
-- Persisting it here lets:
--   * a single backfill pass populate the column without re-deriving on every
--     order placement (Step 4),
--   * the per-user execution lane assert resolved_wallet==stored_wallet on every
--     order build (the #1730 §4 cross-user isolation invariant: refuse to sign
--     if the SDK-resolved wallet drifts from what was persisted at create-time),
--   * the deposit watcher learn the deposit wallet without ad-hoc derivation.
--
-- Mirrors migration 061 (wallets.safe_address) in shape: additive + idempotent,
-- nullable until backfilled. The unique partial index lets the watcher reverse-
-- look up the user from a deposit-wallet transfer once that path goes live.

ALTER TABLE wallets ADD COLUMN IF NOT EXISTS polymarket_deposit_wallet VARCHAR(42);

CREATE UNIQUE INDEX IF NOT EXISTS idx_wallets_polymarket_deposit_wallet
    ON wallets (polymarket_deposit_wallet) WHERE polymarket_deposit_wallet IS NOT NULL;
