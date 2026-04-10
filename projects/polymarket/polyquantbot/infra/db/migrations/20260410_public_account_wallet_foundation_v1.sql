-- public account wallet foundation v1
-- durable entities: users, risk_profiles, trading_accounts, api_credentials, trade_intents

CREATE TABLE IF NOT EXISTS users (
    user_id          TEXT        PRIMARY KEY,
    external_ref     TEXT        NOT NULL DEFAULT '',
    display_name     TEXT        NOT NULL DEFAULT '',
    created_at       DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    updated_at       DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
);

CREATE TABLE IF NOT EXISTS risk_profiles (
    risk_profile_id       TEXT        PRIMARY KEY,
    max_position_ratio    DOUBLE PRECISION NOT NULL DEFAULT 0.10,
    max_concurrent_trades INTEGER     NOT NULL DEFAULT 5,
    daily_loss_limit_usd  DOUBLE PRECISION NOT NULL DEFAULT -2000.0,
    max_drawdown_ratio    DOUBLE PRECISION NOT NULL DEFAULT 0.08,
    config                JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at            DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    updated_at            DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
);

CREATE TABLE IF NOT EXISTS trading_accounts (
    trading_account_id    TEXT        PRIMARY KEY,
    user_id               TEXT        NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    mode                  TEXT        NOT NULL DEFAULT 'paper',
    wallet_type           TEXT        NOT NULL DEFAULT '',
    wallet_address        TEXT        NOT NULL DEFAULT '',
    proxy_wallet_address  TEXT        NOT NULL DEFAULT '',
    funder_address        TEXT        NOT NULL DEFAULT '',
    credential_reference  TEXT        NOT NULL DEFAULT '',
    risk_profile_id       TEXT        NOT NULL REFERENCES risk_profiles(risk_profile_id),
    is_active             BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at            DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    updated_at            DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
);

CREATE TABLE IF NOT EXISTS api_credentials (
    credential_id         TEXT        PRIMARY KEY,
    user_id               TEXT        NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    credential_reference  TEXT        NOT NULL UNIQUE,
    provider              TEXT        NOT NULL DEFAULT 'polymarket',
    auth_type             TEXT        NOT NULL DEFAULT 'placeholder',
    secret_ref            TEXT        NOT NULL DEFAULT '',
    is_active             BOOLEAN     NOT NULL DEFAULT TRUE,
    metadata              JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at            DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    updated_at            DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
);

CREATE TABLE IF NOT EXISTS trade_intents (
    trade_intent_id       TEXT        PRIMARY KEY,
    user_id               TEXT        NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    trading_account_id    TEXT        NOT NULL REFERENCES trading_accounts(trading_account_id) ON DELETE CASCADE,
    mode                  TEXT        NOT NULL,
    market_id             TEXT        NOT NULL,
    side                  TEXT        NOT NULL,
    size                  DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    expected_price        DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    expected_value        DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    strategy_source       TEXT        NOT NULL DEFAULT '',
    status                TEXT        NOT NULL DEFAULT 'recorded',
    metadata              JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at            DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
);
