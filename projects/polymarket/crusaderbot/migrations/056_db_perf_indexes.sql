-- Migration 056: DB performance — add FK indexes, drop unused/duplicate indexes
-- All CREATE INDEX use IF NOT EXISTS; all DROP INDEX use IF EXISTS — fully idempotent.
-- No table locks: CONCURRENTLY not applicable in transaction; these run at boot via
-- migration runner (single-connection, no concurrent load at deploy time).

-- ============================================================
-- 1. Add covering indexes for unindexed foreign keys
--    (hot-path tables first: orders, positions, users)
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_orders_market_id
    ON public.orders (market_id);

CREATE INDEX IF NOT EXISTS idx_positions_market_id
    ON public.positions (market_id);

CREATE INDEX IF NOT EXISTS idx_positions_order_id
    ON public.positions (order_id);

CREATE INDEX IF NOT EXISTS idx_users_referrer_id
    ON public.users (referrer_id);

CREATE INDEX IF NOT EXISTS idx_idempotency_keys_user_id
    ON public.idempotency_keys (user_id);

CREATE INDEX IF NOT EXISTS idx_user_signal_subscriptions_feed_id
    ON public.user_signal_subscriptions (feed_id);

CREATE INDEX IF NOT EXISTS idx_fees_order_id
    ON public.fees (order_id);

CREATE INDEX IF NOT EXISTS idx_fees_referrer_id
    ON public.fees (referrer_id);

CREATE INDEX IF NOT EXISTS idx_copy_trade_events_position_id
    ON public.copy_trade_events (position_id);

-- ============================================================
-- 2. Drop duplicate index (fees table has identical pair)
-- ============================================================

-- idx_fees_trade_id is an exact duplicate of idx_fees_trade (Supabase advisor WARN).
DROP INDEX IF EXISTS public.idx_fees_trade_id;

-- ============================================================
-- 3. Drop confirmed-unused indexes on cold tables
--    (Supabase advisor reports zero scans since creation)
-- ============================================================

-- copy_trade_events — cold table, events written but rarely queried by index
DROP INDEX IF EXISTS public.idx_copy_trade_events_user_id;
DROP INDEX IF EXISTS public.idx_copy_trade_events_market;
DROP INDEX IF EXISTS public.idx_copy_trade_events_created_at;

-- referral system — low-frequency path
DROP INDEX IF EXISTS public.idx_referral_events_referrer;

-- audit tables — append-only, queried by full scan in admin tools
DROP INDEX IF EXISTS public.idx_audit_log_event;
DROP INDEX IF EXISTS public.idx_audit_log_created;

-- mode_change_events — audit-only, low frequency
DROP INDEX IF EXISTS public.idx_mode_change_events_user;
DROP INDEX IF EXISTS public.idx_mode_change_events_reason;

-- redeem_queue — small table, full scans are acceptable
DROP INDEX IF EXISTS public.idx_redeem_queue_failed;

-- fees — already covered by idx_fees_trade; idx_fees_user unused
DROP INDEX IF EXISTS public.idx_fees_user;
