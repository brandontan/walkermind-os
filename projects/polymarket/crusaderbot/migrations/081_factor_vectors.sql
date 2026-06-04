-- 081_factor_vectors.sql
-- WARP-72 Phase 2 prep (WARP•R00T) — durable, queryable labeled dataset for the
-- SMART STRIKE scoring orchestrator. Phase 1 emits the 7-factor vector as logs +
-- candidate metadata (ephemeral, not queryable); Phase 2 must derive weights from
-- a real settled-outcome dataset, so this table is the durable sink.
--
-- GRAIN (critical): ONE row per candle, keyed by condition_id (each candle slot is
-- a distinct Polymarket market = distinct conditionId). NOT one row per scan tick —
-- the recorder UPSERTs latest-wins so many scans of the same candle collapse to one
-- labeled example. Per-tick rows would bloat the table and autocorrelate the
-- dataset, biasing Phase-2 weight derivation.
--
-- LABEL lifecycle:
--   1. Written at the entry-decision point with the PROVISIONAL outcome
--      (open->now from the oracle), outcome_source='provisional', settled=FALSE.
--   2. UPDATED at candle resolution with the realized open->close outcome
--      (oracle price_at(open) vs price_at(close)), outcome_source='open_to_close',
--      settled=TRUE. Joined by condition_id. Phase 2 trains on settled
--      open_to_close rows ONLY.
--
-- A row is written for EVERY evaluated candle (traded or not) so the dataset stays
-- unbiased. Pure shadow telemetry — no FK into trading tables, no capital effect.
-- Writes gated by FACTOR_DATASET_PERSIST_ENABLED. Retention is an operator concern
-- (e.g. DELETE FROM factor_vectors WHERE first_seen_at < NOW() - INTERVAL '180 days').

CREATE TABLE IF NOT EXISTS factor_vectors (
    condition_id          VARCHAR(100) PRIMARY KEY,   -- GRAIN: one row per candle
    market_id             VARCHAR(100) NOT NULL,
    slug                  VARCHAR(160),
    asset                 VARCHAR(16),
    timeframe             VARCHAR(8),
    evaluated_rule        VARCHAR(32),                -- rule of the latest snapshot
    router_selected_rule  VARCHAR(32),                -- rule the router actually picked
    selected_by_router    BOOLEAN NOT NULL DEFAULT FALSE,

    -- The 7 factors (WARP-71 spec) ----------------------------------------------
    momentum              NUMERIC(18,8),              -- rolling repricing velocity (px/s)
    momentum_delta        NUMERIC(18,8),
    momentum_span_sec     NUMERIC(10,3),
    momentum_samples      INTEGER,
    volatility_sigma      NUMERIC(18,10),
    liquidity_usdc        NUMERIC(18,6),
    spread                NUMERIC(10,6),              -- complete-set cost yes_ask+no_ask
    orderbook_depth_usdc  NUMERIC(18,6),
    ttl_sec               NUMERIC(12,3),
    oracle_edge           NUMERIC(12,8),
    oracle_edge_status    VARCHAR(32),
    oracle_would_pass     BOOLEAN,
    oracle_delta          NUMERIC(18,10),

    -- Candidate shape (context) -------------------------------------------------
    fav_side              VARCHAR(4),
    entry_side            VARCHAR(4),
    fav_price             NUMERIC(10,6),
    entry_price           NUMERIC(10,6),
    ask_diff              NUMERIC(10,6),
    complete_set_edge     NUMERIC(10,6),
    underdog_mode         BOOLEAN,

    -- Realized label (provisional at entry-decision; settled at resolution) -----
    realized_outcome      VARCHAR(8),                 -- UP / DOWN / FLAT / NULL
    realized_delta        NUMERIC(18,10),
    outcome_source        VARCHAR(24),                -- provisional | open_to_close | unresolved
    outcome_observed_rem_sec NUMERIC(12,3),
    candle_open_epoch     DOUBLE PRECISION,
    candle_close_epoch    DOUBLE PRECISION,

    -- Settlement bookkeeping ----------------------------------------------------
    open_price            NUMERIC(20,8),
    close_price           NUMERIC(20,8),
    settled               BOOLEAN NOT NULL DEFAULT FALSE,
    settled_at            TIMESTAMPTZ,
    first_seen_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Settlement backfill scans unsettled, closed candles → partial index keeps it cheap.
CREATE INDEX IF NOT EXISTS idx_factor_vectors_unsettled
    ON factor_vectors (candle_close_epoch)
    WHERE settled = FALSE;
-- Phase-2 weight derivation slices by (asset, timeframe) over settled rows.
CREATE INDEX IF NOT EXISTS idx_factor_vectors_settled_asset_tf
    ON factor_vectors (asset, timeframe, outcome_source)
    WHERE settled = TRUE;
CREATE INDEX IF NOT EXISTS idx_factor_vectors_first_seen
    ON factor_vectors (first_seen_at);

-- RLS deny-by-default (repo invariant — every public table; mirrors market_snapshots
-- in migration 080). Telemetry only, no user-identifiable data; the backend service
-- role bypasses RLS to write, anon/authenticated clients get no direct access.
ALTER TABLE factor_vectors ENABLE ROW LEVEL SECURITY;
