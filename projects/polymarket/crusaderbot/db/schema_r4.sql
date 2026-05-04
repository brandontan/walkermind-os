-- CrusaderBot R4 — schema additions for deposit watcher + ledger.
-- Append-only; never destructive to tables created in migrations/001_init.sql.
--
-- Tables added:
--   sub_accounts     — one virtual sub-account per user (1:1 for MVP)
--   ledger_entries   — sub-account scoped append-only ledger
--
-- Notes:
--   * The legacy `ledger` table from 001_init.sql remains untouched (R1 stub).
--   * The existing `deposits` table from 001_init.sql is reused as-is — it
--     already carries (id, user_id, tx_hash UNIQUE, amount_usdc, block_number,
--     swept, confirmed_at, created_at). UNIQUE(tx_hash) is the idempotency
--     guard the deposit watcher relies on. No redefinition here.
--   * Rerun-safe via IF NOT EXISTS guards.

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
