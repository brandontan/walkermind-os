-- migration 065 — reverse Telegram-link (account unification)
--
-- Lane: WARP/ROOT-account-link-telegram (MAJOR)
--
-- WebTrader and the Telegram bot are one account. A Telegram-first user can
-- already reach WebTrader (Telegram Login Widget or link_email). The reverse —
-- an EMAIL-first WebTrader user linking their Telegram — was missing, so using
-- the bot created a SECOND, unsynced account. This migration adds the support
-- for a one-time-code reverse link.
--
-- 1. users.merged_into — tombstone pointer. When a fresh duplicate Telegram
--    account is absorbed into the user's canonical (email) account, the
--    duplicate's telegram_user_id is moved to the canonical account and the
--    duplicate is tombstoned (synthetic unreachable email + merged_into set)
--    rather than deleted (several user FKs lack ON DELETE CASCADE — deletion
--    is unsafe on this money schema). Non-destructive + traceable.
--
-- 2. account_link_codes — short-lived one-time codes minted by WebTrader for
--    the authenticated (email) account and redeemed in the bot via /link.
--
-- Additive, idempotent. No data backfill required.

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS merged_into UUID REFERENCES users(id);

COMMENT ON COLUMN users.merged_into IS
  'Set when this row was a duplicate Telegram account absorbed into the '
  'referenced canonical account (reverse Telegram-link). Tombstoned rows '
  'have no usable login. NULL for all live accounts.';

CREATE TABLE IF NOT EXISTS account_link_codes (
    code         VARCHAR(16) PRIMARY KEY,
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMPTZ NOT NULL,
    consumed_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_account_link_codes_user
  ON account_link_codes(user_id);

COMMENT ON TABLE account_link_codes IS
  'One-time codes for the reverse Telegram-link flow. Minted by WebTrader '
  'POST /api/web/account/link-telegram/start for the authenticated email '
  'account; redeemed in the bot via /link <code>. Short-lived (see '
  'expires_at); single-use (consumed_at).';
