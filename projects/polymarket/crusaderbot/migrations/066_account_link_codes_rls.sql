-- migration 066 — RLS deny-by-default parity for account_link_codes
--
-- Lane: WARP/ROOT-account-link-rls-deeplink
--
-- Migration 065 created public.account_link_codes. New public tables default
-- to RLS DISABLED, which breaks the repo invariant (migration 046: RLS enabled
-- deny-by-default on every public table; security advisor must report zero
-- rls_disabled_in_public). This brings the new table into parity.
--
-- ENABLE only (no FORCE, no policies): anon/authenticated are locked out; the
-- backend reaches the table via service_role / postgres owner, which bypass
-- RLS. Mirrors the migration 046 pattern. Additive + idempotent.

ALTER TABLE account_link_codes ENABLE ROW LEVEL SECURITY;
