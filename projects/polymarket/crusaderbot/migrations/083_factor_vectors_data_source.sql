-- WARP-77 Phase 1.4 — factor_vectors provenance column.
--
-- Tags each factor_vectors row with the DATA REGIME it was captured under so
-- paper-on-synthetic, paper-on-real-CLOB, and live-on-real-CLOB samples are
-- separable downstream (the WARP-78 scorer/EV work must not mix synthetic and
-- real-CLOB rows). Values:
--   paper_synthetic — paper sizing on the legacy/synthetic data path (default;
--                     matches every historical row)
--   paper_real      — paper sizing on the real CLOB v2 backend (USE_PYSDK_CLOB)
--   live_real       — real capital path armed (ENABLE_LIVE_TRADING)
--
-- IDEMPOTENT: run_migrations() executes every migrations/*.sql on each restart,
-- so every statement here is guarded (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).
-- The column is NOT NULL DEFAULT 'paper_synthetic', so adding it backfills all
-- existing rows to the historical default with zero NULLs.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'factor_data_source') THEN
        CREATE TYPE factor_data_source AS ENUM ('paper_synthetic', 'paper_real', 'live_real');
    END IF;
END$$;

ALTER TABLE factor_vectors
    ADD COLUMN IF NOT EXISTS data_source factor_data_source NOT NULL DEFAULT 'paper_synthetic';

-- Defensive backfill: if a prior partial run added the column nullable, normalize
-- any NULL to the historical default. No-op once the NOT NULL default is in place.
UPDATE factor_vectors SET data_source = 'paper_synthetic' WHERE data_source IS NULL;

CREATE INDEX IF NOT EXISTS idx_factor_vectors_data_source
    ON factor_vectors (data_source);
