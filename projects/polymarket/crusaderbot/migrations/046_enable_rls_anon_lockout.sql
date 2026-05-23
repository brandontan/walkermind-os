-- 046_enable_rls_anon_lockout.sql
--
-- SECURITY: Enable Row Level Security on every public table to revoke the
-- implicit full read/write access held by the Supabase `anon` and
-- `authenticated` roles. The Supabase advisor flagged all 42 public tables as
-- RLS-disabled, meaning anyone holding the project anon key could read or
-- mutate every row (users, wallets, positions, orders, ledger, ...).
--
-- WHY THIS IS SAFE FOR THE BACKEND (verified before authoring):
--   * All 42 public tables are owned by role `postgres`.
--   * `postgres` and `service_role` both have rolbypassrls = TRUE.
--   * The bot/webtrader backend connects via DATABASE_URL as `postgres`
--     (it ran every CREATE TABLE migration in this directory, so it is the
--     table owner). A table owner bypasses RLS unless FORCE is set.
--   * The webtrader frontend never touches Supabase directly — it talks to
--     the backend API + SSE (/api/web/*). No client uses the anon key.
--
-- Therefore: ENABLE (not FORCE) RLS + no permissive policies = deny-by-default
-- for anon/authenticated, while the backend keeps full access. The anon key is
-- locked out with zero impact on the running application.
--
-- Deliberately NO policies are created: there is no legitimate anon/authenticated
-- consumer, so the secure default is "no policy = no access" for those roles.
-- If a direct-from-browser Supabase data path is ever added, scoped policies
-- (e.g. user rows by auth.uid()) must be designed at that time.
--
-- Idempotent: ENABLE ROW LEVEL SECURITY on an already-enabled table is a no-op.
-- Reversible: ALTER TABLE public.<t> DISABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    t text;
    targets text[] := ARRAY[
        'idempotency_keys', 'user_signal_subscriptions', 'positions',
        'portfolio_snapshots', 'execution_queue', 'copy_trade_idempotency',
        'users', 'referral_codes', 'redeem_queue', 'job_runs',
        'hd_index_counter', 'fills', 'wallets', 'copy_trade_events',
        'markets', 'fees', 'referral_events', 'strategy_definitions',
        'ledger', 'live_redemptions', 'orders', 'user_risk_profile',
        'signal_feeds', 'user_settings', 'fee_config', 'user_tiers',
        'leaderboard_stats', 'copy_trade_daily_spend', 'chain_cursor',
        'kill_switch', 'system_flags', 'risk_log', 'copy_targets',
        'system_alerts', 'deposits', 'signal_publications', 'copy_trade_tasks',
        'system_settings', 'user_strategies', 'kill_switch_history',
        'mode_change_events', 'audit_log'
    ];
BEGIN
    FOREACH t IN ARRAY targets LOOP
        IF EXISTS (
            SELECT 1 FROM pg_tables
             WHERE schemaname = 'public' AND tablename = t
        ) THEN
            EXECUTE format(
                'ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t
            );
        ELSE
            RAISE NOTICE 'skipping RLS enable: table public.% not found', t;
        END IF;
    END LOOP;
END
$$;
