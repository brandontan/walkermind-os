-- Migration 022: Referral + Share + Fee system prep
-- referral_codes, referral_events, fees, fee_config tables.
-- Fee collection and referral payout guards remain OFF; logic is gated.

BEGIN;

-- Referral codes: one per user, 8-char alphanumeric, unique.
CREATE TABLE IF NOT EXISTS referral_codes (
    id              BIGSERIAL   PRIMARY KEY,
    user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code            VARCHAR(12) NOT NULL,
    uses            INT         NOT NULL DEFAULT 0,
    referred_users  INT         NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT referral_codes_code_unique UNIQUE (code),
    CONSTRAINT referral_codes_user_unique UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS idx_referral_codes_user
    ON referral_codes (user_id);

CREATE INDEX IF NOT EXISTS idx_referral_codes_code
    ON referral_codes (code);

-- Referral events: each new-user join that carried a ref param.
CREATE TABLE IF NOT EXISTS referral_events (
    id              BIGSERIAL   PRIMARY KEY,
    referrer_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    referred_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code            VARCHAR(12) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT referral_events_referred_unique UNIQUE (referred_id)
);

CREATE INDEX IF NOT EXISTS idx_referral_events_referrer
    ON referral_events (referrer_id, created_at DESC);

-- Fees: per-trade fee record (populated when FEE_COLLECTION_ENABLED=true).
CREATE TABLE IF NOT EXISTS fees (
    id              BIGSERIAL   PRIMARY KEY,
    user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    trade_id        UUID        REFERENCES positions(id) ON DELETE SET NULL,
    gross_pnl       NUMERIC(18, 6) NOT NULL,
    fee_amount      NUMERIC(18, 6) NOT NULL,
    net_pnl         NUMERIC(18, 6) NOT NULL,
    collected_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fees_user
    ON fees (user_id, collected_at DESC);

CREATE INDEX IF NOT EXISTS idx_fees_trade
    ON fees (trade_id);

-- Fee config: single-row config table, seeded with default 10% fee.
CREATE TABLE IF NOT EXISTS fee_config (
    id              INT         PRIMARY KEY DEFAULT 1,
    fee_pct         DECIMAL(5, 4) NOT NULL DEFAULT 0.10,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fee_config_single_row CHECK (id = 1)
);

INSERT INTO fee_config (id, fee_pct) VALUES (1, 0.10)
    ON CONFLICT (id) DO NOTHING;

COMMIT;
