-- 079_module_robustness.sql
-- Phase-2c-1 — Monte Carlo robustness classification per strategy module.
--
-- Stores the latest ROBUST / FRAGILE / UNTRADEABLE / INSUFFICIENT_DATA verdict
-- for each (module, risk_profile), computed by domain/research/robustness from
-- the realized PnL distribution in `positions`. The LIVE-eligibility gate reads
-- the latest row; an UNTRADEABLE module is paper-only, FRAGILE is size-down.
-- Pure analytics artifact — no FK into trading tables, safe to recompute.

CREATE TABLE IF NOT EXISTS module_robustness (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    module             VARCHAR(64)  NOT NULL,
    risk_profile       VARCHAR(20)  NOT NULL,
    classification     VARCHAR(20)  NOT NULL,   -- ROBUST | FRAGILE | UNTRADEABLE | INSUFFICIENT_DATA
    sample_size        INTEGER      NOT NULL DEFAULT 0,
    ev_per_trade       NUMERIC(10,6),           -- mean realized return fraction (pnl/size)
    ruin_probability   NUMERIC(6,5),            -- P(equity <= ruin floor) over the horizon
    p95_max_drawdown   NUMERIC(6,5),            -- 95th-pct max drawdown fraction across paths
    p95_losing_streak  INTEGER,
    mode               VARCHAR(10)  NOT NULL DEFAULT 'paper',  -- which positions fed the sample
    computed_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    -- UNIQUE auto-creates the (module, risk_profile, mode) index that the
    -- live-eligibility lookup uses — no separate index needed.
    UNIQUE (module, risk_profile, mode)
);
