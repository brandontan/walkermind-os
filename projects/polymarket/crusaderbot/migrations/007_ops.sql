-- 007_ops.sql — R12f operator-dashboard / kill-switch / job-monitor backplane.
--
-- Three additive tables, all idempotent:
--
--   system_settings      Key/value bag for operator-flipped runtime flags.
--                        Single row per key. Risk gate step [1] reads
--                        ('kill_switch_active','true'|'false') from here on
--                        every gate evaluation (cached 30s in process to keep
--                        the read non-blocking).
--
--   kill_switch_history  Append-only history of every pause / resume / lock
--                        operator action. INSERT-only from the app — never
--                        UPDATE, never DELETE. Lets WARP🔹CMD reconstruct who
--                        flipped the switch and when, without touching the
--                        general-purpose audit.log.
--
--   job_runs             Last-N scheduler job outcomes. Populated by the
--                        APScheduler listener registered in setup_scheduler().
--                        /ops_dashboard surfaces the most recent rows so the
--                        operator can see whether market_sync, deposit_watch,
--                        signal_scan, exit_watch, and redeem are healthy.

CREATE TABLE IF NOT EXISTS system_settings (
    key        VARCHAR(100) PRIMARY KEY,
    value      TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed the kill-switch keys exactly once. INSERT … ON CONFLICT DO NOTHING
-- keeps the migration idempotent and never overwrites an active state on
-- redeploy: if the operator paused the switch before a deploy, the post-deploy
-- run must not silently flip it back to inactive.
INSERT INTO system_settings (key, value)
VALUES
    ('kill_switch_active', 'false'),
    ('kill_switch_lock_mode', 'false')
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS kill_switch_history (
    id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action    VARCHAR(20) NOT NULL,
    actor_id  BIGINT,
    reason    TEXT,
    ts        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kill_switch_history_ts
    ON kill_switch_history(ts DESC);

CREATE TABLE IF NOT EXISTS job_runs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_name    VARCHAR(100) NOT NULL,
    status      VARCHAR(20) NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    error       TEXT
);

CREATE INDEX IF NOT EXISTS idx_job_runs_started_at
    ON job_runs(started_at DESC);

CREATE INDEX IF NOT EXISTS idx_job_runs_status
    ON job_runs(status, started_at DESC);
