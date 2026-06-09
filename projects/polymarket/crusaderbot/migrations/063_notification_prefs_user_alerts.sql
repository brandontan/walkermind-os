-- Migration 063: per-user notification preferences + per-user alert routing
--
-- 1. user_settings.notification_prefs — JSONB blob storing per-alert-key + per-channel
--    delivery preferences. Shape:
--      {"trade_opened": {"web": true, "tg": true}, "kill_switch": {"web": true, "tg": false}, …}
--    Missing keys / channels default to true (both channels on). Empty default = '{}'.
--    The application layer (webtrader/backend/notification_prefs.py) is the
--    single source of truth for shape + defaults; this column is intentionally
--    free-form JSONB so adding new alert keys does not need a migration.
--
-- 2. system_alerts.user_id — nullable UUID that scopes an alert to one user.
--    NULL = broadcast (existing operator-pushed banners), populated = per-user
--    (trade-lifecycle events, kill switch, etc.). The /api/web/alerts endpoint
--    returns: WHERE user_id IS NULL OR user_id = $1.
--
-- 3. cb_alerts NOTIFY payload now includes user_id so the SSE layer can route
--    per-user alerts to only the connected client that owns them.
--
-- All changes additive + idempotent — paper-safe, no read path breaks.

ALTER TABLE user_settings
  ADD COLUMN IF NOT EXISTS notification_prefs JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE system_alerts
  ADD COLUMN IF NOT EXISTS user_id UUID;

CREATE INDEX IF NOT EXISTS idx_system_alerts_user_active
  ON system_alerts (user_id, created_at DESC)
  WHERE dismissed = FALSE AND user_id IS NOT NULL;

CREATE OR REPLACE FUNCTION _cb_notify_system_alerts()
RETURNS TRIGGER LANGUAGE plpgsql
SET search_path = public, pg_catalog
AS $$
BEGIN
    PERFORM pg_notify(
        'cb_alerts',
        json_build_object(
            'event',    TG_OP,
            'id',       NEW.id::text,
            'severity', NEW.severity,
            'user_id',  CASE WHEN NEW.user_id IS NULL THEN NULL ELSE NEW.user_id::text END
        )::text
    );
    RETURN NEW;
END;
$$;
