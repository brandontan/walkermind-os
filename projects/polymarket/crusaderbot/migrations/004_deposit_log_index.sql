-- 004_deposit_log_index.sql
-- Fix: a single Polygon tx can emit multiple USDC Transfer logs to different
-- tracked deposit addresses. With UNIQUE(tx_hash) only the first log was
-- credited; subsequent logs in the same tx were silently dropped as duplicates,
-- under-crediting users. Make uniqueness (tx_hash, log_index) so every log in
-- the same tx is treated as a distinct deposit row.

ALTER TABLE deposits
    ADD COLUMN IF NOT EXISTS log_index INTEGER NOT NULL DEFAULT 0;

ALTER TABLE deposits
    DROP CONSTRAINT IF EXISTS deposits_tx_hash_key;

ALTER TABLE deposits
    ADD CONSTRAINT deposits_tx_hash_log_index_key
    UNIQUE (tx_hash, log_index);
