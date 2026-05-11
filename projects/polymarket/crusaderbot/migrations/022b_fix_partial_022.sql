-- 022b: Fix partial migration 022
-- Safe to run: uses IF NOT EXISTS and IF EXISTS checks

-- referral_events (missing)
CREATE TABLE IF NOT EXISTS referral_events (
    id BIGSERIAL PRIMARY KEY,
    referrer_user_id BIGINT NOT NULL,
    referred_user_id BIGINT NOT NULL,
    code VARCHAR(12) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_referral_events_referrer
    ON referral_events(referrer_user_id);
CREATE INDEX IF NOT EXISTS idx_referral_events_referred
    ON referral_events(referred_user_id);

-- fee_config (missing)
CREATE TABLE IF NOT EXISTS fee_config (
    id SERIAL PRIMARY KEY,
    fee_pct DECIMAL(5,4) NOT NULL DEFAULT 0.10,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
INSERT INTO fee_config (fee_pct)
    SELECT 0.10 WHERE NOT EXISTS (SELECT 1 FROM fee_config);

-- fees table conflict: add missing columns if not present
ALTER TABLE fees ADD COLUMN IF NOT EXISTS gross_pnl DECIMAL(20,8);
ALTER TABLE fees ADD COLUMN IF NOT EXISTS fee_amount DECIMAL(20,8);
ALTER TABLE fees ADD COLUMN IF NOT EXISTS net_pnl DECIMAL(20,8);
ALTER TABLE fees ADD COLUMN IF NOT EXISTS collected_at TIMESTAMPTZ DEFAULT NOW();

-- Record in schema_migrations
INSERT INTO schema_migrations (version, applied_at)
    VALUES ('022b', NOW())
    ON CONFLICT (version) DO NOTHING;
