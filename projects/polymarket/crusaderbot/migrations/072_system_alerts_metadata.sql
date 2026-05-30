-- 072_system_alerts_metadata.sql
-- Add structured fields to system_alerts so the WebTrader AlertCenter can
-- render typed cards (trade open / closed / TP / SL / risk / system) instead
-- of dumping the Telegram-formatted ASCII text body verbatim.
--
-- `alert_kind` is a short discriminator the frontend renders by:
--   'trade_opened' | 'trade_closed' | 'tp_hit' | 'sl_hit' | 'manual_close'
--   'emergency_close' | 'copy_trade_opened' | 'risk' | 'system'
-- (lowercase, snake_case — matches NotificationEvent / alert_key vocab.)
--
-- `metadata` carries event-specific structured fields (market_label, side,
-- size_usdc, entry_price, exit_price, tp_pct, sl_pct, pnl_usdc, strategy,
-- mode, market_id, position_id). Body remains for legacy / system messages.
--
-- Additive + backfill-safe: alert_kind defaults to NULL on existing rows
-- (frontend falls back to body rendering). New writes set alert_kind +
-- metadata so post-migration alerts render as typed cards.

ALTER TABLE system_alerts
    ADD COLUMN IF NOT EXISTS alert_kind TEXT,
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Index alert_kind for the AlertCenter "by-kind" filter (cheap; low-cardinality).
CREATE INDEX IF NOT EXISTS system_alerts_alert_kind_idx
    ON system_alerts (alert_kind)
    WHERE alert_kind IS NOT NULL;
