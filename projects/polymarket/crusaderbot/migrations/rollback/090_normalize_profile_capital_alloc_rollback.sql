-- Rollback for migration 090 (normalize non-custom profile capital_alloc_pct).
-- NOT auto-run: run_migrations() globs migrations/*.sql at the top level only.
-- Apply manually to revert.
--
-- IMPORTANT — BEST-EFFORT, NON-LOSSLESS. Migration 090 overwrote any drifted
-- per-row capital_alloc_pct with the canonical per-profile default; the prior
-- (drifted) values are not preserved, so a perfect restore is not possible.
-- There is no single "previous" value to restore to. This script is a no-op
-- placeholder documenting that the revert path is: revert the sizing/gate code
-- (so capital_alloc_pct is no longer consumed) — the column value then becomes
-- inert again, matching pre-090 behaviour, without needing a data change.
--
-- SCOPE: touches ``user_settings`` ONLY. Does NOT touch ``positions``.

-- (intentionally no UPDATE — see note above)
SELECT 1;
