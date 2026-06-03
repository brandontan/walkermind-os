-- 080_market_snapshots.sql
-- Phase-2c-2 — per-scan full-universe market snapshot (walk-forward substrate).
--
-- Captures the raw Gamma market universe each scan tick prices — BEFORE any
-- strategy filtering — so the future walk-forward replay (Lane 2c-3) can re-run
-- the real signal → router → gate path over the actual historical market state
-- with no selection bias and no parallel sim logic. Pure append-only telemetry;
-- no FK into trading tables. `raw` keeps the full upstream dict for fidelity so
-- the replay is not limited to the columns extracted here.
--
-- Retention is an operator concern: prune rows older than the desired backtest
-- horizon (e.g. DELETE FROM market_snapshots WHERE scanned_at < NOW() - INTERVAL
-- '90 days'). Writes are gated by SCAN_SNAPSHOT_ENABLED (default OFF).

CREATE TABLE IF NOT EXISTS market_snapshots (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_run_id    UUID,                         -- scan_runs.id (loose link, no FK)
    market_id      VARCHAR(100) NOT NULL,
    category       VARCHAR(64),
    best_bid       NUMERIC(10,6),
    best_ask       NUMERIC(10,6),
    mid_price      NUMERIC(10,6),
    liquidity_usdc NUMERIC(18,6),
    raw            JSONB,
    scanned_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_market_snapshots_scanned_at
    ON market_snapshots (scanned_at);
CREATE INDEX IF NOT EXISTS idx_market_snapshots_market_time
    ON market_snapshots (market_id, scanned_at);
CREATE INDEX IF NOT EXISTS idx_market_snapshots_run
    ON market_snapshots (scan_run_id);
