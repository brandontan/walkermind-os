-- migration 069 — per-user alerts acknowledgement watermark
--
-- Lane: WARP/R00T/strategy-toggle-ui-followup-2 (MINOR — surface persistence)
--
-- Background: WebTrader's AlertCenter "Mark all read" only persisted to the
-- user's browser localStorage. A second device, a private window, or any
-- localStorage clear (quota eviction, OS reset, browser update) would
-- resurface every previously-acknowledged alert on next refresh — the exact
-- "I mark all read but they come back" symptom the owner reported after the
-- WARP/R00T/strategy-toggle-ui-followup deploy.
--
-- This column persists the timestamp of the most recent "Mark all read"
-- click. /alerts filters created_at > alerts_ack_at server-side so the bell
-- count stays cleared across devices, and DashboardSummary surfaces the
-- value so the frontend can mirror the same filter on the closed-position
-- alert stream (which is fetched via /positions, not /alerts).
--
-- NULL = never acknowledged → no filter applied (FAIL-SAFE: a brand-new
-- user sees every alert that arrived since their account was created).

ALTER TABLE user_settings
  ADD COLUMN IF NOT EXISTS alerts_ack_at TIMESTAMPTZ NULL;

COMMENT ON COLUMN user_settings.alerts_ack_at IS
  'Watermark for AlertCenter Mark all read. Rows with created_at <= alerts_ack_at are hidden from /alerts and from the closed-position alert stream.';
