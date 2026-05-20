-- Migration 044: Drop access_tier column from users table
-- access_tier is planned for removal — access control will move to a role-based model.
-- WARNING: DO NOT APPLY. Column is still referenced in Python code per WARP-50 audit
--          (see reports/forge/fix-drop-access-tier-warp50.md section 6).
--          Apply only after the role-based Python migration lane lands.
-- Idempotent: IF EXISTS guard prevents error on re-run once safe to apply.

ALTER TABLE users DROP COLUMN IF EXISTS access_tier;
