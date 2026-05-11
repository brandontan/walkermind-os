-- 022b: Fix partial migration 022
-- Safe to run: uses IF NOT EXISTS and conditional DO blocks

-- Fix referral_events if previously created with wrong BIGINT schema
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'referral_events'
          AND column_name = 'referrer_user_id'
    ) THEN
        -- DROP COLUMN also drops any indexes on those columns automatically
        ALTER TABLE referral_events DROP COLUMN referrer_user_id;
        ALTER TABLE referral_events DROP COLUMN referred_user_id;
        ALTER TABLE referral_events ADD COLUMN referrer_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE;
        ALTER TABLE referral_events ADD COLUMN referred_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE;
        ALTER TABLE referral_events ADD CONSTRAINT referral_events_referred_unique UNIQUE (referred_id);
    END IF;
END $$;

-- referral_events: create with correct UUID schema if missing
CREATE TABLE IF NOT EXISTS referral_events (
    id          BIGSERIAL   PRIMARY KEY,
    referrer_id UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    referred_id UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code        VARCHAR(12) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT referral_events_referred_unique UNIQUE (referred_id)
);
CREATE INDEX IF NOT EXISTS idx_referral_events_referrer
    ON referral_events (referrer_id, created_at DESC);

-- fee_config (missing)
CREATE TABLE IF NOT EXISTS fee_config (
    id         SERIAL      PRIMARY KEY,
    fee_pct    DECIMAL(5,4) NOT NULL DEFAULT 0.10,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO fee_config (fee_pct)
    SELECT 0.10 WHERE NOT EXISTS (SELECT 1 FROM fee_config);

-- fees table conflict: add missing columns if not present
ALTER TABLE fees ADD COLUMN IF NOT EXISTS gross_pnl    DECIMAL(20,8);
ALTER TABLE fees ADD COLUMN IF NOT EXISTS fee_amount   DECIMAL(20,8);
ALTER TABLE fees ADD COLUMN IF NOT EXISTS net_pnl      DECIMAL(20,8);
ALTER TABLE fees ADD COLUMN IF NOT EXISTS collected_at TIMESTAMPTZ DEFAULT NOW();
