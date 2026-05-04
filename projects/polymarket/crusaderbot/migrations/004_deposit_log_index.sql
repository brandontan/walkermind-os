-- 004_deposit_log_index.sql
-- Fix: a single Polygon tx can emit multiple USDC Transfer logs to different
-- tracked deposit addresses. With UNIQUE(tx_hash) only the first log was
-- credited; subsequent logs in the same tx were silently dropped as duplicates,
-- under-crediting users. Make uniqueness (tx_hash, log_index) so every log in
-- the same tx is treated as a distinct deposit row.
--
-- Idempotency: PostgreSQL ALTER TABLE ADD CONSTRAINT does not support
-- IF NOT EXISTS, so each statement is wrapped in a DO $$ guard. This file
-- must be safe to run multiple times — run_migrations re-executes it on
-- every startup.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'deposits'
        AND column_name = 'log_index'
    ) THEN
        ALTER TABLE deposits
            ADD COLUMN log_index INTEGER NOT NULL DEFAULT 0;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'deposits_tx_hash_key'
    ) THEN
        ALTER TABLE deposits
            DROP CONSTRAINT deposits_tx_hash_key;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'deposits_tx_hash_log_index_key'
    ) THEN
        ALTER TABLE deposits
            ADD CONSTRAINT deposits_tx_hash_log_index_key
            UNIQUE (tx_hash, log_index);
    END IF;
END $$;
