-- Migration 051: email/password auth support
--
-- Adds optional email + password_hash to users so accounts can be created
-- and authenticated without Telegram. Existing Telegram-only accounts are
-- unaffected — telegram_user_id stays populated, email stays NULL.
--
-- telegram_user_id becomes nullable so web-only registrations are possible.
-- The UNIQUE constraint is preserved (two Telegram accounts cannot share a row).

-- 1. Make telegram_user_id nullable (was NOT NULL). Safe to run twice.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='users' AND column_name='telegram_user_id' AND is_nullable='NO'
  ) THEN
    ALTER TABLE users ALTER COLUMN telegram_user_id DROP NOT NULL;
  END IF;
END$$;

-- 2. Add email (unique, nullable — NULL for Telegram-only accounts).
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS email        TEXT,
  ADD COLUMN IF NOT EXISTS password_hash TEXT;

-- Unique index allows multiple NULLs (SQL standard) while enforcing
-- uniqueness among non-NULL emails.
CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique
  ON users (email)
  WHERE email IS NOT NULL;

-- 3. Enforce: every user must have at least one identity (Telegram OR email).
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE constraint_name = 'users_identity_required'
      AND table_name = 'users'
  ) THEN
    ALTER TABLE users
      ADD CONSTRAINT users_identity_required
      CHECK (telegram_user_id IS NOT NULL OR email IS NOT NULL);
  END IF;
END$$;
