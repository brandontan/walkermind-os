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

-- Seed the kill-switch keys exactly once. The block is idempotent — on
-- re-run it does nothing because the keys already exist — AND it
-- backfills from the legacy ``kill_switch`` table on first migration so
-- a deploy onto a DB where the operator had paused via the pre-R12f
-- code path inherits the paused state instead of silently re-opening
-- trading. The latest row in ``kill_switch`` (ORDER BY id DESC LIMIT 1)
-- is the authoritative legacy state.
-- Two-instance rolling deploys can race on this seed. Both transactions
-- pass the IF NOT EXISTS check, then the second INSERT raises a unique-
-- key error and aborts startup. ``ON CONFLICT (key) DO NOTHING`` makes
-- the seed idempotent under concurrency. The IF NOT EXISTS guard is
-- still useful — it skips the (cheap) backfill SELECT against the
-- legacy ``kill_switch`` table on every redeploy after the first.
DO $$
DECLARE
    legacy_active BOOLEAN := FALSE;
    has_legacy_table BOOLEAN;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM system_settings WHERE key = 'kill_switch_active'
    ) THEN
        SELECT to_regclass('public.kill_switch') IS NOT NULL
          INTO has_legacy_table;
        IF has_legacy_table THEN
            SELECT COALESCE(active, FALSE) INTO legacy_active
              FROM kill_switch ORDER BY id DESC LIMIT 1;
        END IF;
        INSERT INTO system_settings (key, value) VALUES (
            'kill_switch_active',
            CASE WHEN legacy_active THEN 'true' ELSE 'false' END
        )
        ON CONFLICT (key) DO NOTHING;
    END IF;

    INSERT INTO system_settings (key, value)
    VALUES ('kill_switch_lock_mode', 'false')
    ON CONFLICT (key) DO NOTHING;
END $$;

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
