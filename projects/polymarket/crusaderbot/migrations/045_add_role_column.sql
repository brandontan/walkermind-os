-- Migration 045: Add role column to users table (WARP-50b)
-- Two-role access model: 'admin' = full owner access, 'user' = standard paper trading.
-- Paper trading is open to every user; live trading requires role='admin'
-- (plus the activation guards in domain/execution/live.assert_live_guards).
--
-- Legacy SMALLINT tier column remains in the schema for now — it is no longer
-- read by any access-gating code path but is still written on INSERT to avoid
-- breaking the NOT NULL constraint. Migration 044_drop_access_tier.sql removes
-- the column once this lane has been stable in production.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS + conditional admin backfill.

ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'user';

-- Bootstrap: promote the earliest-created user to admin so a fresh DB has
-- at least one operator capable of running /allowlist and live-trading
-- flows. No-op once any user already has role='admin' (covers reruns and
-- DBs already seeded via scripts/seed_operator_tier.py).
UPDATE users
   SET role = 'admin'
 WHERE id = (
     SELECT id FROM users ORDER BY created_at ASC LIMIT 1
 )
   AND NOT EXISTS (SELECT 1 FROM users WHERE role = 'admin');
