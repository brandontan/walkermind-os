-- WARP-78 label fix — factor_vectors safe_close-horizon realized label.
--
-- Phase 0 found the open→close label is biased for force-exit rules. safe_close
-- force-exits ~30s before candle close, so its realized label is the underlying
-- direction open→(close − 30s), NOT open→close. These additive columns persist
-- that horizon's outcome alongside the existing open→close label (computed at
-- settlement from the same oracle ring), so the EV trainer/A/B can judge safe_close
-- at its real exit — and so it stops sharing close_sweep's identical label
-- (breaking the close_sweep≡safe_close degeneracy when the underlying moved in the
-- final 30s). close_sweep (~8s ≈ close) and flip_hunter (hold-to-settlement) keep
-- the open→close label.
--
-- Additive + nullable (NULL when the close−30s tick isn't in the ring — honest,
-- like the open→close label). IDEMPOTENT: run_migrations re-runs every *.sql.

ALTER TABLE factor_vectors
    ADD COLUMN IF NOT EXISTS realized_outcome_safe_close VARCHAR(8),
    ADD COLUMN IF NOT EXISTS realized_delta_safe_close   NUMERIC(18,10);
