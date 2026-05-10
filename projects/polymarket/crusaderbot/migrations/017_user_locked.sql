-- Migration 017: per-user account lock flag
-- Supports operator-only account freeze without touching the kill switch.
-- Additive idempotent — safe to run on an already-migrated database.
ALTER TABLE users ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT false;

-- Rollback DDL (run manually if needed):
-- ALTER TABLE users DROP COLUMN IF EXISTS locked;
