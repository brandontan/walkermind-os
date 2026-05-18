-- Migration 027: add notifications_on column to user_settings
-- Required by the V6 settings hub notification toggle.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS notifications_on BOOLEAN NOT NULL DEFAULT TRUE;

-- Rollback:
-- ALTER TABLE user_settings DROP COLUMN IF EXISTS notifications_on;
