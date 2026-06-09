-- 086_strategy_scan_observations.sql
-- WARP-80 sub-lane 1a — Weather + Playbook scan observability.
--
-- Per-scan-tick near-miss telemetry for the two opportunistic strategies that
-- book zero entries by design (weather, playbook). For every market that reaches
-- a binding edge filter we persist HOW FAR it was from passing and whether it
-- WOULD pass at relaxed thresholds (-10% / -25% / -50%), plus the dark/live feed
-- state. This surfaces the binding constraint into the DB so the threshold-tuning
-- analysis (sub-lane 1b) no longer depends on Fly DEBUG-log access.
--
-- Pure append-only observability: written fail-soft AFTER the strategy returns,
-- never on the trading path. No selection/threshold/risk behaviour changes. The
-- caller gates writes behind SCAN_OBSERVABILITY_ENABLED (default ON).
--
-- Retention is an operator concern: prune rows older than the desired analysis
-- horizon (e.g. DELETE FROM strategy_scan_observations WHERE observed_at <
-- NOW() - INTERVAL '30 days').

CREATE TABLE IF NOT EXISTS strategy_scan_observations (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_run_id             UUID,                  -- scan_runs.id (loose link, no FK)
    strategy                VARCHAR(32)  NOT NULL, -- 'weather' | 'playbook' | sub-module
    market_id               VARCHAR(100) NOT NULL,
    zero_reason             VARCHAR(48),           -- re-emit of the scan_runs reason
    binding_filter          VARCHAR(32),           -- 'ev' | 'price' | 'quality' | 'router_abstain'
    metric_value            NUMERIC(18,8),         -- candidate value on the binding metric
    threshold               NUMERIC(18,8),         -- the gate threshold it was measured against
    distance_to_threshold   NUMERIC(18,8),         -- signed gap toward passing (>=0 passes)
    would_pass_at_threshold JSONB NOT NULL DEFAULT '{}',  -- {"-10%": bool, "-25%": bool, "-50%": bool}
    module_state            VARCHAR(16),           -- 'live' | 'null_feed' | 'disabled'
    observed_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategy_scan_obs_observed_at
    ON strategy_scan_observations (observed_at);
CREATE INDEX IF NOT EXISTS idx_strategy_scan_obs_strategy_time
    ON strategy_scan_observations (strategy, observed_at);
CREATE INDEX IF NOT EXISTS idx_strategy_scan_obs_binding
    ON strategy_scan_observations (strategy, binding_filter, observed_at);

-- RLS deny-by-default (repo invariant — every public table; mirrors scan_runs in
-- migration 055 and market_snapshots in 080). Telemetry only, no user-identifiable
-- data; the backend service role bypasses RLS to write, anon/authenticated clients
-- get no direct access.
ALTER TABLE strategy_scan_observations ENABLE ROW LEVEL SECURITY;
