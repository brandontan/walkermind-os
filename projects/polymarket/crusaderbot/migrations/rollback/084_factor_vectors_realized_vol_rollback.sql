-- Rollback for migration 084 (WARP-78 Phase 1 — factor_vectors.realized_vol).
-- NOT auto-run: run_migrations() globs migrations/*.sql at the top level only.
-- Apply manually to revert.

ALTER TABLE factor_vectors DROP COLUMN IF EXISTS realized_vol;
