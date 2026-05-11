-- 023 user_tiers: string-based access tier (FREE / PREMIUM / ADMIN)
-- Additive only. Does not alter any existing table.

CREATE TABLE IF NOT EXISTS user_tiers (
    id          SERIAL      PRIMARY KEY,
    user_id     BIGINT      UNIQUE NOT NULL,
    tier        VARCHAR(10) NOT NULL DEFAULT 'FREE',
    assigned_by BIGINT,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT user_tiers_valid_tier CHECK (tier IN ('FREE', 'PREMIUM', 'ADMIN'))
);

CREATE INDEX IF NOT EXISTS idx_user_tiers_user_id ON user_tiers (user_id);
