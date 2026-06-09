-- Migration 059: Pin search_path on all public functions
-- Fixes: function_search_path_mutable WARN (Supabase security advisor)
-- Risk: MINOR — no logic change, only configuration parameter

ALTER FUNCTION public._cb_notify_fills()                     SET search_path = public, pg_catalog;
ALTER FUNCTION public._cb_notify_orders()                    SET search_path = public, pg_catalog;
ALTER FUNCTION public._cb_notify_portfolio_snapshots()       SET search_path = public, pg_catalog;
ALTER FUNCTION public._cb_notify_positions()                 SET search_path = public, pg_catalog;
ALTER FUNCTION public._cb_notify_system_alerts()             SET search_path = public, pg_catalog;
ALTER FUNCTION public._cb_notify_system_settings()          SET search_path = public, pg_catalog;
ALTER FUNCTION public._cb_notify_user_settings()             SET search_path = public, pg_catalog;
ALTER FUNCTION public.positions_reject_applied_tpsl_update() SET search_path = public, pg_catalog;
ALTER FUNCTION public.positions_snapshot_applied_tpsl()      SET search_path = public, pg_catalog;
