-- 015_order_lifecycle.sql
-- Phase 4C order lifecycle bookkeeping.
--
-- Adds the columns the OrderLifecycleManager needs to record fill /
-- cancel / expiry / stale state on the orders row, plus a dedicated
-- `fills` table that captures every individual fill returned by
-- broker GET /orders/{id}/fills polls. Existing rows are left
-- untouched: every column is additive with safe defaults, every CREATE
-- is guarded by IF NOT EXISTS so re-applying the migration on a fresh
-- boot is a no-op.
--
-- Idempotency:
--   * ADD COLUMN IF NOT EXISTS — Postgres native, safe to re-run.
--   * CREATE TABLE IF NOT EXISTS — same.
--   * CREATE INDEX IF NOT EXISTS — same.
-- The migration runner executes every *.sql file in
-- migrations/ alphabetically on every boot; this file MUST stay
-- idempotent indefinitely.
--
-- ROLLBACK: see DROP block at the bottom of this file. Operator-
-- executed via psql against a stopped bot instance.

-- ---------------------------------------------------------------------------
-- orders: lifecycle terminal-state columns
-- ---------------------------------------------------------------------------

ALTER TABLE orders ADD COLUMN IF NOT EXISTS filled_at      TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS cancelled_at   TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS expired_at     TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS fill_price     NUMERIC(10,6);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS fill_size      NUMERIC(18,6);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS poll_attempts  INTEGER NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS last_polled_at TIMESTAMPTZ;

-- Lifecycle scans target rows whose status is still in-flight; a
-- partial index on the open lifecycle states keeps the scan cheap as
-- the orders table grows.
CREATE INDEX IF NOT EXISTS idx_orders_lifecycle_open
    ON orders (status, last_polled_at NULLS FIRST)
    WHERE status IN ('submitted', 'pending');

-- ---------------------------------------------------------------------------
-- fills: per-fill broker rows
-- ---------------------------------------------------------------------------
--
-- One row per (order_id, fill_id) tuple; ``fill_id`` is the broker-
-- assigned trade id and is globally unique on the broker side. We
-- enforce uniqueness on ``fill_id`` directly so duplicate-poll inserts
-- are dropped via ON CONFLICT DO NOTHING in the lifecycle manager.

CREATE TABLE IF NOT EXISTS fills (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id    UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    fill_id     VARCHAR(200) NOT NULL UNIQUE,
    price       NUMERIC(10,6) NOT NULL,
    size        NUMERIC(18,6) NOT NULL,
    side        VARCHAR(5) NOT NULL,
    fill_ts     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw         JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fills_order ON fills (order_id);
CREATE INDEX IF NOT EXISTS idx_fills_ts    ON fills (fill_ts);

-- ---------------------------------------------------------------------------
-- ROLLBACK (operator-executed, NOT applied by the runner)
-- ---------------------------------------------------------------------------
--
-- BEGIN;
-- DROP INDEX IF EXISTS idx_fills_ts;
-- DROP INDEX IF EXISTS idx_fills_order;
-- DROP TABLE IF EXISTS fills;
-- DROP INDEX IF EXISTS idx_orders_lifecycle_open;
-- ALTER TABLE orders DROP COLUMN IF EXISTS last_polled_at;
-- ALTER TABLE orders DROP COLUMN IF EXISTS poll_attempts;
-- ALTER TABLE orders DROP COLUMN IF EXISTS fill_size;
-- ALTER TABLE orders DROP COLUMN IF EXISTS fill_price;
-- ALTER TABLE orders DROP COLUMN IF EXISTS expired_at;
-- ALTER TABLE orders DROP COLUMN IF EXISTS cancelled_at;
-- ALTER TABLE orders DROP COLUMN IF EXISTS filled_at;
-- COMMIT;
