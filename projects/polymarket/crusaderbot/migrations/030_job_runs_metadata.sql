-- 030_job_runs_metadata.sql
-- Add metadata JSONB column to job_runs for per-job structured output.
--
-- exit_watch uses this to record RunResult counts (submitted/expired/held/errors)
-- so operators can query per-tick activity without parsing log files.
-- Idempotent: ADD COLUMN IF NOT EXISTS is safe on re-run.

ALTER TABLE job_runs
    ADD COLUMN IF NOT EXISTS metadata JSONB;
