-- Migration 028: Add preset_activated_at to user_settings
-- Required by Phase 5 UX Rebuild — tracks when user activated a preset.
-- Idempotent via ADD COLUMN IF NOT EXISTS.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS preset_activated_at TIMESTAMPTZ;

-- Rollback:
-- ALTER TABLE user_settings DROP COLUMN IF EXISTS preset_activated_at;
