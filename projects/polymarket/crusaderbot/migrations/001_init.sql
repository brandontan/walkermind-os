-- CrusaderBot — initial schema for R1 skeleton.
-- All tables created in order respecting FK dependencies.
-- Rerun-safe via run_migrations() existence check on `users`.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE users (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_user_id BIGINT UNIQUE NOT NULL,
    username         VARCHAR(100),
    access_tier      SMALLINT NOT NULL DEFAULT 1,
    auto_trade_on    BOOLEAN NOT NULL DEFAULT FALSE,
    referrer_id      UUID REFERENCES users(id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE sessions (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX idx_sessions_user ON sessions(user_id);

CREATE TABLE wallets (
    user_id         UUID PRIMARY KEY REFERENCES users(id),
    deposit_address VARCHAR(42) UNIQUE NOT NULL,
    hd_index        INTEGER UNIQUE NOT NULL,
    encrypted_key   TEXT NOT NULL,
    balance_usdc    NUMERIC(18,6) NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE deposits (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id),
    tx_hash      VARCHAR(66) UNIQUE NOT NULL,
    amount_usdc  NUMERIC(18,6) NOT NULL,
    block_number BIGINT,
    swept        BOOLEAN NOT NULL DEFAULT FALSE,
    confirmed_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_deposits_user ON deposits(user_id);
CREATE INDEX idx_deposits_swept ON deposits(swept) WHERE swept = FALSE;

CREATE TABLE ledger (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id),
    type        VARCHAR(30) NOT NULL,
    amount_usdc NUMERIC(18,6) NOT NULL,
    ref_id      UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ledger_user ON ledger(user_id);

CREATE TABLE user_settings (
    user_id           UUID PRIMARY KEY REFERENCES users(id),
    risk_profile      VARCHAR(20) NOT NULL DEFAULT 'balanced',
    strategy_types    TEXT[] NOT NULL DEFAULT ARRAY['copy_trade'],
    category_filters  TEXT[],
    blacklist_markets TEXT[],
    capital_alloc_pct NUMERIC(5,4) NOT NULL DEFAULT 0.50,
    tp_pct            NUMERIC(5,4),
    sl_pct            NUMERIC(5,4),
    auto_redeem_mode  VARCHAR(10) NOT NULL DEFAULT 'hourly',
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE copy_targets (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users(id),
    wallet_address VARCHAR(42) NOT NULL,
    scale_factor   NUMERIC(5,4) NOT NULL DEFAULT 1.0,
    enabled        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, wallet_address)
);

CREATE TABLE markets (
    id             VARCHAR(100) PRIMARY KEY,
    slug           VARCHAR(300),
    question       TEXT,
    category       VARCHAR(50),
    status         VARCHAR(20) NOT NULL DEFAULT 'active',
    yes_price      NUMERIC(10,6),
    no_price       NUMERIC(10,6),
    liquidity_usdc NUMERIC(18,2),
    resolution_at  TIMESTAMPTZ,
    synced_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_markets_status ON markets(status);
CREATE INDEX idx_markets_category ON markets(category);

CREATE TABLE orders (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id),
    market_id           VARCHAR(100) NOT NULL REFERENCES markets(id),
    side                VARCHAR(5) NOT NULL,
    size_usdc           NUMERIC(18,6) NOT NULL,
    price               NUMERIC(10,6) NOT NULL,
    mode                VARCHAR(10) NOT NULL DEFAULT 'paper',
    status              VARCHAR(20) NOT NULL DEFAULT 'pending',
    idempotency_key     VARCHAR(100) UNIQUE NOT NULL,
    polymarket_order_id VARCHAR(200),
    strategy_type       VARCHAR(30),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_orders_user ON orders(user_id);
CREATE INDEX idx_orders_status ON orders(status);

CREATE TABLE positions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id),
    market_id     VARCHAR(100) NOT NULL REFERENCES markets(id),
    order_id      UUID REFERENCES orders(id),
    side          VARCHAR(5) NOT NULL,
    size_usdc     NUMERIC(18,6) NOT NULL,
    entry_price   NUMERIC(10,6) NOT NULL,
    current_price NUMERIC(10,6),
    tp_pct        NUMERIC(5,4),
    sl_pct        NUMERIC(5,4),
    mode          VARCHAR(10) NOT NULL DEFAULT 'paper',
    status        VARCHAR(20) NOT NULL DEFAULT 'open',
    exit_reason   VARCHAR(30),
    pnl_usdc      NUMERIC(18,6),
    opened_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at     TIMESTAMPTZ
);
CREATE INDEX idx_positions_user ON positions(user_id);
CREATE INDEX idx_positions_status ON positions(status);

CREATE TABLE risk_log (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id),
    market_id  VARCHAR(100),
    gate_step  SMALLINT NOT NULL,
    approved   BOOLEAN NOT NULL,
    reason     VARCHAR(200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_risklog_user ON risk_log(user_id);

CREATE TABLE idempotency_keys (
    key        VARCHAR(100) PRIMARY KEY,
    user_id    UUID NOT NULL REFERENCES users(id),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE fees (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id       UUID REFERENCES orders(id),
    user_id        UUID NOT NULL REFERENCES users(id),
    fee_usdc       NUMERIC(18,6) NOT NULL DEFAULT 0,
    referrer_id    UUID REFERENCES users(id),
    referrer_share NUMERIC(18,6) NOT NULL DEFAULT 0,
    collected      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE referral_codes (
    user_id    UUID PRIMARY KEY REFERENCES users(id),
    code       VARCHAR(20) UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE kill_switch (
    id         SERIAL PRIMARY KEY,
    active     BOOLEAN NOT NULL DEFAULT FALSE,
    reason     TEXT,
    changed_by UUID,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO kill_switch (active) VALUES (FALSE);

CREATE SCHEMA IF NOT EXISTS audit;
CREATE TABLE audit.log (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ts         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id    UUID,
    actor_role VARCHAR(20) NOT NULL,
    action     VARCHAR(100) NOT NULL,
    payload    JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_audit_ts ON audit.log(ts);
CREATE INDEX idx_audit_user ON audit.log(user_id);
