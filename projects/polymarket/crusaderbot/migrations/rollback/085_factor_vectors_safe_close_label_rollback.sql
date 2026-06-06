-- Rollback for migration 085 (WARP-78 safe_close-horizon label).
-- NOT auto-run: run_migrations() globs migrations/*.sql at the top level only.
-- Apply manually to revert.

ALTER TABLE factor_vectors
    DROP COLUMN IF EXISTS realized_outcome_safe_close,
    DROP COLUMN IF EXISTS realized_delta_safe_close;
