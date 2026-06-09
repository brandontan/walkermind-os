-- migration 064 — per-user live-trading capital cap
--
-- Lane: WARP/ROOT-live-activation-flow (Axis #3, MAJOR)
--
-- Adds ``user_settings.live_capital_cap_usdc``: the maximum aggregate USDC
-- the user permits the bot to deploy across LIVE positions at any one
-- time. Zero means the user has not yet opted in to live trading — risk
-- gate step 15 rejects any live trade for a user whose cap is zero, and
-- rejects any live trade that would push aggregate live exposure past the
-- cap.
--
-- Default 0 — safe-by-default. Existing users see no behaviour change
-- (their live trades, if any were enabled, would now require the user
-- to set a cap via /api/web/live/enable). Paper trading is unaffected.
--
-- Additive, idempotent, no data backfill required.

ALTER TABLE user_settings
  ADD COLUMN IF NOT EXISTS live_capital_cap_usdc NUMERIC(12, 6)
    NOT NULL
    DEFAULT 0
    CHECK (live_capital_cap_usdc >= 0);

COMMENT ON COLUMN user_settings.live_capital_cap_usdc IS
  'Per-user max USDC the bot may deploy in LIVE mode (aggregate across '
  'open live positions). 0 = live trading disabled for this user. Set '
  'via /api/web/live/enable (typed-confirm flow) or Telegram /enable_live.';
