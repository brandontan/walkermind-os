-- #1805 Polymarket Bridge / pUSD settlement audit substrate.
-- This migration is schema-only. It does not enable user-facing native USDC or
-- USDT by itself; runtime code may credit live balance only from terminal
-- Bridge COMPLETED records whose target is Polygon pUSD.

CREATE TABLE IF NOT EXISTS bridge_deposit_addresses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    polymarket_wallet_address TEXT NOT NULL,
    evm_address TEXT,
    svm_address TEXT,
    btc_address TEXT,
    tvm_address TEXT,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, polymarket_wallet_address)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_bridge_deposit_addresses_evm
    ON bridge_deposit_addresses (LOWER(evm_address))
    WHERE evm_address IS NOT NULL;

CREATE TABLE IF NOT EXISTS bridge_deposit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    bridge_address TEXT NOT NULL,
    from_chain_id TEXT NOT NULL,
    from_token_address TEXT NOT NULL,
    from_token_symbol TEXT,
    from_amount_base_unit TEXT NOT NULL,
    from_token_decimals INTEGER NOT NULL DEFAULT 6,
    to_chain_id TEXT NOT NULL,
    to_token_address TEXT NOT NULL,
    status TEXT NOT NULL,
    tx_hash TEXT,
    normalized_amount_usdc NUMERIC(18,6),
    credited_deposit_id UUID REFERENCES deposits(id),
    raw JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    manual_review_reason TEXT,
    CONSTRAINT bridge_deposit_events_status_chk CHECK (
        status IN (
            'DEPOSIT_DETECTED', 'PROCESSING', 'ORIGIN_TX_CONFIRMED',
            'SUBMITTED', 'COMPLETED', 'FAILED', 'EXPIRED', 'CANCELLED',
            'CANCELED', 'ERROR', 'MANUAL_REVIEW'
        )
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_bridge_deposit_events_tx_hash
    ON bridge_deposit_events (tx_hash)
    WHERE tx_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_bridge_deposit_events_user_status
    ON bridge_deposit_events (user_id, status, updated_at DESC);

ALTER TABLE bridge_deposit_addresses ENABLE ROW LEVEL SECURITY;
ALTER TABLE bridge_deposit_events ENABLE ROW LEVEL SECURITY;
