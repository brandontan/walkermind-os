-- WARP-94: credit-neutral wrong-token (native USDC) deposit alerts.
--
-- Native USDC (0x3c499c…) is NOT Polymarket's CTF collateral (USDC.e is, see
-- config.USDC_POLYGON). The deposit watcher detects transfers of native USDC to
-- user deposit addresses purely to ALERT the user — those funds are NEVER
-- credited (a distinct ERC-20, untradeable on Polymarket without a swap). This
-- table makes the alert idempotent (one alert per on-chain transfer) and gives
-- operators an audit trail for manual recovery. It carries no balance and feeds
-- nothing into the ledger.
CREATE TABLE IF NOT EXISTS wrong_token_deposits (
    id            BIGSERIAL PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES users(id),
    token_address TEXT NOT NULL,
    tx_hash       TEXT NOT NULL,
    log_index     INTEGER NOT NULL,
    amount        NUMERIC NOT NULL,
    block_number  BIGINT,
    alerted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT wrong_token_deposits_tx_hash_log_index_key UNIQUE (tx_hash, log_index)
);

-- Mirror the repo-wide anon-lockout posture (migration 046): every public table
-- has RLS enabled; the bot connects with a privileged role that bypasses it.
ALTER TABLE wrong_token_deposits ENABLE ROW LEVEL SECURITY;

-- Independent scan cursor so the wrong-token pass advances separately from the
-- USDC.e credit pass and can never interfere with deposit crediting.
INSERT INTO chain_cursor (name, block_number) VALUES ('usdc_native_deposits', 0)
ON CONFLICT (name) DO NOTHING;
