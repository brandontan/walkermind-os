-- Migration 044: Drop access_tier column from users table.
--
-- Re-enabled by WARP-51 after every Python writer of access_tier was removed
-- (users.py, services/user_service.py, scripts/seed_demo_data.py;
-- scripts/seed_operator_tier.py was deleted). Role gating runs entirely on
-- users.role (see migration 045_add_role_column.sql).
--
-- History: a prior production attempt of this migration crashed Fly because
-- the live image still wrote access_tier=4 on INSERT. The column was restored
-- by 045b_restore_access_tier_placeholder. WARP-51 removes those writes; this
-- DROP is now safe to apply on the next deploy.

ALTER TABLE users DROP COLUMN IF EXISTS access_tier;
