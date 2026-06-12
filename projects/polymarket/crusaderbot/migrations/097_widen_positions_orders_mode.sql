-- live-enable mode truncation fix (warp/root-live-enable-mode-truncation).
-- Self-serve PAPER -> LIVE (live_mode.enable_live_self_serve) archives paper
-- simulation rows by setting positions.mode / orders.mode = 'paper_archived'
-- (14 chars). Both columns were VARCHAR(10) from 001_init, so the write threw
-- StringDataRightTruncationError and rolled back the ENTIRE /api/web/live/enable
-- transaction — the live switch was broken in production (Sentry
-- DAWN-SNOWFLAKE-1729-33/34). Widen both to VARCHAR(20). Increasing a varchar
-- length limit is a catalog-only change in Postgres (no table rewrite,
-- brief lock only). Idempotent: guarded on the current declared length.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'positions' AND column_name = 'mode'
          AND character_maximum_length < 20
    ) THEN
        ALTER TABLE public.positions ALTER COLUMN mode TYPE VARCHAR(20);
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'orders' AND column_name = 'mode'
          AND character_maximum_length < 20
    ) THEN
        ALTER TABLE public.orders ALTER COLUMN mode TYPE VARCHAR(20);
    END IF;
END $$;
