-- WARP-78 Phase 1 — factor_vectors realized-volatility column.
--
-- Phase 0 found volatility_sigma is a DEAD per-asset config constant (std collapses
-- to 0 → weight 0 in the scorer). This column persists the REAL rolling realized
-- volatility (per sqrt-second) of the YES-mid price series, measured at entry from
-- the momentum ring, so WARP-78 Phase 1 can correlate it with realized EV.
--
-- Additive + nullable (NULL = "not enough history yet" — never a fabricated zero).
-- IDEMPOTENT: run_migrations() re-runs every migrations/*.sql each boot.

ALTER TABLE factor_vectors
    ADD COLUMN IF NOT EXISTS realized_vol NUMERIC(18,10);
