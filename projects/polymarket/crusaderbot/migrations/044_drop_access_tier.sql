-- Migration 044: Drop access_tier column from users table
-- access_tier is obsolete — access control is now role-based (admin/user).
-- Safe to run: column is no longer referenced in any Python code or migration.
-- Idempotent: IF EXISTS guard prevents error on re-run.

ALTER TABLE users DROP COLUMN IF EXISTS access_tier;
