-- CrusaderBot R4 — schema additions for deposit watcher + ledger.
-- Append-only; never destructive to data in tables created in
-- migrations/001_init.sql.
--
-- Tables added:
--   sub_accounts     — one virtual sub-account per user (1:1 for MVP)
--   ledger_entries   — sub-account scoped append-only ledger
--
-- Mutations to existing tables (idempotent, additive only — no data loss):
--   deposits  — add log_index column + composite UNIQUE (tx_hash, log_index)
--               replacing the original UNIQUE (tx_hash). One EVM tx can emit
--               multiple Transfer events, distinguished by log_index, so the
--               original constraint silently dropped legitimate credits when
--               two recipients shared one transaction.
--
-- Notes:
--   * The legacy `ledger` table from 001_init.sql remains untouched (R1 stub).
--   * Rerun-safe via IF NOT EXISTS guards + constraint-existence checks.

CREATE TABLE IF NOT EXISTS sub_accounts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id)
);
CREATE INDEX IF NOT EXISTS idx_sub_accounts_user ON sub_accounts(user_id);

CREATE TABLE IF NOT EXISTS ledger_entries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sub_account_id  UUID NOT NULL REFERENCES sub_accounts(id),
    type            VARCHAR(30) NOT NULL,
    amount_usdc     NUMERIC(18,6) NOT NULL,
    ref_id          UUID,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ledger_entries_sub_account
    ON ledger_entries(sub_account_id);
CREATE INDEX IF NOT EXISTS idx_ledger_entries_ts
    ON ledger_entries(ts);

-- deposits: log_index + composite unique (replaces UNIQUE(tx_hash) only).
ALTER TABLE deposits ADD COLUMN IF NOT EXISTS log_index INTEGER NOT NULL DEFAULT 0;

DO $$
BEGIN
    -- Drop the original auto-named UNIQUE on tx_hash if it exists. Older
    -- deployments may have run R1 init and now need this constraint relaxed.
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'deposits'::regclass
          AND conname = 'deposits_tx_hash_key'
    ) THEN
        ALTER TABLE deposits DROP CONSTRAINT deposits_tx_hash_key;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'deposits'::regclass
          AND conname = 'deposits_tx_hash_log_index_key'
    ) THEN
        ALTER TABLE deposits ADD CONSTRAINT deposits_tx_hash_log_index_key
            UNIQUE (tx_hash, log_index);
    END IF;
END $$;

