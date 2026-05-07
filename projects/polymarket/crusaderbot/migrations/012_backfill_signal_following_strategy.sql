-- 012_backfill_signal_following_strategy.sql
-- Backfill user_strategies enrollment for all existing active signal_following
-- subscribers who predate the subscribe/unsubscribe enrollment fix (P3d).
--
-- Any user with at least one active user_signal_subscriptions row and no
-- existing user_strategies row gets a new enabled row so the scan loop picks
-- them up.  DO NOTHING preserves rows that already exist — including rows
-- that an operator intentionally disabled — so this backfill is non-sticky:
-- it fills gaps only and does not override explicit disables on restart.
--
-- Idempotency: safe to re-run on startup.

INSERT INTO user_strategies (user_id, strategy_name, weight, enabled)
SELECT DISTINCT user_id, 'signal_following', 1.0, TRUE
  FROM user_signal_subscriptions
 WHERE unsubscribed_at IS NULL
ON CONFLICT (user_id, strategy_name) DO NOTHING;
