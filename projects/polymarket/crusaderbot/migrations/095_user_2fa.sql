-- 095: self-serve TOTP 2FA infrastructure (closes the documented gap in
-- live_checklist._gate_two_factor — "self-serve 2FA infrastructure does
-- not yet exist; operator must manually flip system_settings flag").
--
-- After this lane, a user enrolls via the webtrader CONFIG tab:
--   1. POST /api/web/2fa/setup → generates a TOTP secret (RFC 6238), stores
--      it Fernet-encrypted on user_settings.totp_secret_encrypted, returns
--      the provisioning URI for the user's authenticator app.
--   2. POST /api/web/2fa/verify {code} → validates the 6-digit code, sets
--      user_settings.totp_enabled=true AND writes system_settings key
--      ``2fa_enabled:{user_id}``='true' (keeping the existing live_checklist
--      gate read-side byte-compatible, no domain/activation change needed).
--   3. /live/status → gate 7 now passes automatically.
--
-- Additive + idempotent. Nullable until the user enrolls — a user with NULL
-- totp_secret_encrypted is "not enrolled"; once enrolled the flag drives the
-- gate.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS totp_secret_encrypted TEXT,
    ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN NOT NULL DEFAULT FALSE;
