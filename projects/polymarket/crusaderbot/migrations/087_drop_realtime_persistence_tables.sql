-- 087_drop_realtime_persistence_tables.sql
-- WARP-82 — kill durable real-time persistence (post-incident remediation).
--
-- Operator architecture ruling (Mr. Walker): "Sinyal real-time gk perlu simpan
-- ke database." These four unbounded log/snapshot tables filled the Supabase
-- Free-tier 500 MB quota and triggered a platform read-only lock → migration
-- failure → boot loop (~8h P0). Their write paths are removed in this lane
-- (job_tracker / risk gate / heisenberg sync / scan snapshots now emit to
-- stdout + Sentry instead of the DB), and the operator job-status surface reads
-- an in-memory ring. With zero remaining writers, the durable tables are dropped.
--
-- Idempotent (IF EXISTS). CASCADE: these are leaf telemetry tables; the only
-- inbound FK is risk_log.user_id -> users.id (an OUTBOUND ref FROM risk_log),
-- so dropping cannot damage users or any other retained table. A pre-drop grep
-- (Phase 0) found no FK from a retained table INTO any of these four.
--
-- A one-off snapshot of pre-drop contents was taken into
-- _warp82_backup_<table> before this migration (operator backup); those backup
-- tables can be dropped once verification is complete.

DROP TABLE IF EXISTS market_snapshots CASCADE;
DROP TABLE IF EXISTS heisenberg_realtime_trades CASCADE;
DROP TABLE IF EXISTS risk_log CASCADE;

-- job_runs is NOT dropped here: its WRITER is already killed (job_tracker now
-- emits structured logs + an in-memory ring), so it no longer grows — but three
-- operator surfaces still read it via raw SQL (jobs/hourly_report.py,
-- bot/handlers/health.py, bot/handlers/settings.py). Dropping it now would make
-- those queries error. Its drop is a small follow-up once those readers are
-- repointed to the in-memory ring (the table sits frozen + tiny meanwhile).
-- DROP TABLE IF EXISTS job_runs CASCADE;  -- deferred (see above)
