-- Rollback for migration 083 (WARP-77 Phase 1.4 — factor_vectors.data_source).
--
-- NOT auto-run: run_migrations() globs migrations/*.sql at the top level only
-- (non-recursive), so files under migrations/rollback/ are never executed on
-- startup. Apply manually (psql / Supabase SQL editor) only to revert 083.
--
-- Safe + idempotent. Order matters: drop the index and column before the type.

DROP INDEX IF EXISTS idx_factor_vectors_data_source;

ALTER TABLE factor_vectors DROP COLUMN IF EXISTS data_source;

DROP TYPE IF EXISTS factor_data_source;
