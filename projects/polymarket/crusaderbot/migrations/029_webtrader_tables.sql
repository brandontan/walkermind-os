-- Migration 029: WebTrader dashboard tables + LISTEN/NOTIFY triggers
-- Idempotent: safe to run multiple times.

-- portfolio_snapshots: periodic equity/PnL snapshots per user (drives PnL chart)
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    balance_usdc   NUMERIC(18,6) NOT NULL DEFAULT 0,
    equity_usdc    NUMERIC(18,6) NOT NULL DEFAULT 0,
    pnl_today      NUMERIC(18,6) NOT NULL DEFAULT 0,
    pnl_7d         NUMERIC(18,6) NOT NULL DEFAULT 0,
    open_positions INTEGER NOT NULL DEFAULT 0,
    snapshot_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_user_at
    ON portfolio_snapshots (user_id, snapshot_at DESC);

-- system_alerts: operator-pushed alerts surfaced in the dashboard
CREATE TABLE IF NOT EXISTS system_alerts (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    severity     VARCHAR(10) NOT NULL DEFAULT 'info'
                 CHECK (severity IN ('info', 'warning', 'critical')),
    title        TEXT NOT NULL,
    body         TEXT,
    dismissed    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_system_alerts_active
    ON system_alerts (created_at DESC)
    WHERE dismissed = FALSE;

-- ── NOTIFY trigger functions ──────────────────────────────────────────────────
-- Channel naming: cb_<table>
-- Payload always includes: event (INSERT|UPDATE), user_id (UUID string), id (UUID string)
-- SSE layer routes per user_id; broadcast channels (cb_system_settings, cb_alerts)
-- fan out to all connected users.

CREATE OR REPLACE FUNCTION _cb_notify_orders()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify(
        'cb_orders',
        json_build_object(
            'event',   TG_OP,
            'user_id', NEW.user_id::text,
            'id',      NEW.id::text,
            'status',  NEW.status
        )::text
    );
    RETURN NEW;
END;
$$;

-- fills has no user_id — includes order_id for async resolution in SSE layer
CREATE OR REPLACE FUNCTION _cb_notify_fills()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify(
        'cb_fills',
        json_build_object(
            'event',    TG_OP,
            'order_id', NEW.order_id::text,
            'id',       NEW.id::text
        )::text
    );
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION _cb_notify_positions()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify(
        'cb_positions',
        json_build_object(
            'event',   TG_OP,
            'user_id', NEW.user_id::text,
            'id',      NEW.id::text,
            'status',  NEW.status
        )::text
    );
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION _cb_notify_user_settings()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify(
        'cb_user_settings',
        json_build_object(
            'event',   TG_OP,
            'user_id', NEW.user_id::text
        )::text
    );
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION _cb_notify_system_settings()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify(
        'cb_system_settings',
        json_build_object(
            'event', TG_OP,
            'key',   NEW.key
        )::text
    );
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION _cb_notify_portfolio_snapshots()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify(
        'cb_portfolio',
        json_build_object(
            'event',   TG_OP,
            'user_id', NEW.user_id::text,
            'id',      NEW.id::text
        )::text
    );
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION _cb_notify_system_alerts()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify(
        'cb_alerts',
        json_build_object(
            'event',    TG_OP,
            'id',       NEW.id::text,
            'severity', NEW.severity
        )::text
    );
    RETURN NEW;
END;
$$;

-- ── Trigger bindings (DROP IF EXISTS + CREATE for idempotency) ────────────────

DROP TRIGGER IF EXISTS trg_cb_orders ON orders;
CREATE TRIGGER trg_cb_orders
    AFTER INSERT OR UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION _cb_notify_orders();

DROP TRIGGER IF EXISTS trg_cb_fills ON fills;
CREATE TRIGGER trg_cb_fills
    AFTER INSERT ON fills
    FOR EACH ROW EXECUTE FUNCTION _cb_notify_fills();

DROP TRIGGER IF EXISTS trg_cb_positions ON positions;
CREATE TRIGGER trg_cb_positions
    AFTER INSERT OR UPDATE ON positions
    FOR EACH ROW EXECUTE FUNCTION _cb_notify_positions();

DROP TRIGGER IF EXISTS trg_cb_user_settings ON user_settings;
CREATE TRIGGER trg_cb_user_settings
    AFTER INSERT OR UPDATE ON user_settings
    FOR EACH ROW EXECUTE FUNCTION _cb_notify_user_settings();

DROP TRIGGER IF EXISTS trg_cb_system_settings ON system_settings;
CREATE TRIGGER trg_cb_system_settings
    AFTER INSERT OR UPDATE ON system_settings
    FOR EACH ROW EXECUTE FUNCTION _cb_notify_system_settings();

DROP TRIGGER IF EXISTS trg_cb_portfolio_snapshots ON portfolio_snapshots;
CREATE TRIGGER trg_cb_portfolio_snapshots
    AFTER INSERT ON portfolio_snapshots
    FOR EACH ROW EXECUTE FUNCTION _cb_notify_portfolio_snapshots();

DROP TRIGGER IF EXISTS trg_cb_system_alerts ON system_alerts;
CREATE TRIGGER trg_cb_system_alerts
    AFTER INSERT OR UPDATE ON system_alerts
    FOR EACH ROW EXECUTE FUNCTION _cb_notify_system_alerts();
