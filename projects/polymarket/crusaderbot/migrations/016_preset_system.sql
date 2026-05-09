-- 016_preset_system.sql
-- Phase 5C strategy preset system.
--
-- Adds two columns to user_settings so the named-preset selection survives
-- bot restarts and the preset's per-position cap can be enforced alongside
-- existing capital_alloc_pct / tp_pct / sl_pct fields.
--
-- The preset selection itself is the new piece of state. The other preset
-- values (strategies, capital, TP, SL) reuse columns that already exist on
-- user_settings so the preset record is an authoritative reference, not a
-- duplicated source of truth.
--
-- active_preset      = preset key the user last activated (e.g. 'whale_mirror')
--                      NULL when no preset has been picked.
-- max_position_pct   = preset's per-trade position cap (fraction). NULL when
--                      no preset is active. The risk gate's hard ceiling is
--                      enforced separately in domain/risk; this is only the
--                      preset-level user-visible cap and may not exceed the
--                      hard cap in domain/risk/constants.py.
--
-- Idempotency: every ALTER uses IF NOT EXISTS so re-applying is a no-op.
-- Every existing row gets NULL for the new columns, preserving prior config.
--
-- ROLLBACK: see commented block at the bottom.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS active_preset    VARCHAR(50);

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS max_position_pct NUMERIC(5,4);

-- Cheap lookup for the scheduler / dashboards when filtering users by
-- whichever preset they picked. Partial index keeps it tiny.
CREATE INDEX IF NOT EXISTS idx_user_settings_active_preset
    ON user_settings(active_preset)
    WHERE active_preset IS NOT NULL;

-- ROLLBACK (manual, operator-only):
--   ALTER TABLE user_settings DROP COLUMN IF EXISTS active_preset;
--   ALTER TABLE user_settings DROP COLUMN IF EXISTS max_position_pct;
--   DROP INDEX IF EXISTS idx_user_settings_active_preset;
