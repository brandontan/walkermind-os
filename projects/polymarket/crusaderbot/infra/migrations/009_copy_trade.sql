-- 009_copy_trade.sql
-- Phase 3b copy-trade strategy persistence layer.
--
-- Adds two tables that back the CopyTradeStrategy:
--   copy_targets       — per-user list of leader wallet addresses being
--                        mirrored. The application enforces a hard cap of 3
--                        active rows per user at the Telegram handler layer;
--                        this table does NOT carry a check constraint for the
--                        cap (cardinality enforcement belongs in the handler
--                        path so the user gets an actionable error message
--                        rather than a Postgres constraint exception).
--   copy_trade_events  — append-only log of leader trades the strategy has
--                        already mirrored. The UNIQUE constraint on
--                        (copy_target_id, source_tx_hash) is the dedup
--                        boundary: the strategy reads per-follower so the
--                        same leader trade may legitimately be mirrored by
--                        multiple followers (each row has its own
--                        copy_target_id), while a re-scan for the same
--                        follower is short-circuited. The downstream
--                        consumer that persists rows is protected by the
--                        constraint as a second line of defence against a
--                        race between concurrent scans for the same
--                        follower.
--
-- Idempotency: every CREATE statement uses IF NOT EXISTS. The migration is
-- safe to re-run on every startup (matches the 008_strategy_tables.sql and
-- 006_redeem_queue.sql patterns).
--
-- Path note: this file lives at projects/polymarket/crusaderbot/infra/migrations/
-- per WARP🔹CMD task spec for P3a/P3b. The current `database.run_migrations()`
-- runner reads from `migrations/` (sibling directory). WARP🔹CMD resolves the
-- runner path divergence in a follow-up lane — see P3a known-issues note.

-- ---------------------------------------------------------------------------
-- copy_targets: per-user leader wallets being mirrored.
--
-- Schema reconciliation note. ``001_init.sql`` already creates ``copy_targets``
-- with the legacy column set ``(wallet_address, enabled, last_seen_tx,
-- scale_factor)``. The legacy ``bot/handlers/setup.py`` writes via
-- ``wallet_address`` + ``enabled`` and is still on disk. This migration:
--
--   * creates the table with the P3b column set if (and only if) it does not
--     exist (fresh DB);
--   * adds the P3b columns idempotently if the legacy table is already
--     present (upgraded DB);
--   * backfills ``target_wallet_address`` from the legacy ``wallet_address``
--     column and ``status`` from the legacy ``enabled`` boolean so existing
--     rows are visible to the P3b strategy code path;
--   * drops the NOT NULL on the legacy ``wallet_address`` column so future
--     P3b inserts that only populate ``target_wallet_address`` succeed
--     under the legacy schema. Both columns are kept on the table — the
--     legacy reader and the new strategy reader operate on disjoint subsets
--     of rows (legacy rows have wallet_address, P3b rows have
--     target_wallet_address) until a follow-up lane retires the legacy path.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS copy_targets (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_wallet_address    VARCHAR(42) NOT NULL,
    scale_factor             DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    status                   VARCHAR(20) NOT NULL DEFAULT 'active',
    trades_mirrored          INTEGER NOT NULL DEFAULT 0,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, target_wallet_address)
);

-- Idempotent column adds for the legacy schema (001_init.sql).
ALTER TABLE copy_targets
    ADD COLUMN IF NOT EXISTS target_wallet_address VARCHAR(42);
ALTER TABLE copy_targets
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active';
ALTER TABLE copy_targets
    ADD COLUMN IF NOT EXISTS trades_mirrored INTEGER NOT NULL DEFAULT 0;

-- Backfill P3b columns from legacy columns. The DO blocks are guarded on
-- column presence so this runs cleanly on both fresh DBs (legacy columns
-- absent — backfill is a no-op) and upgraded DBs (legacy columns present
-- — rows are migrated forward).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'copy_targets'
           AND column_name = 'wallet_address'
    ) THEN
        UPDATE copy_targets
           SET target_wallet_address = wallet_address
         WHERE target_wallet_address IS NULL;
        -- Drop NOT NULL on wallet_address so future P3b INSERTs that
        -- only populate target_wallet_address do not raise. The column
        -- remains on the table for the legacy setup.py reader.
        BEGIN
            ALTER TABLE copy_targets ALTER COLUMN wallet_address DROP NOT NULL;
        EXCEPTION WHEN others THEN
            -- Column may already be nullable or otherwise constrained
            -- in a way that makes the DROP NOT NULL a no-op.
            NULL;
        END;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'copy_targets'
           AND column_name = 'enabled'
    ) THEN
        UPDATE copy_targets
           SET status = CASE WHEN enabled THEN 'active' ELSE 'inactive' END
         WHERE status IS NULL OR status = 'active';
    END IF;
END $$;

-- Lock target_wallet_address NOT NULL only after backfill, so legacy DBs
-- with NULL target_wallet_address rows do not blow up the migration.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM copy_targets WHERE target_wallet_address IS NULL
    ) THEN
        BEGIN
            ALTER TABLE copy_targets
                ALTER COLUMN target_wallet_address SET NOT NULL;
        EXCEPTION WHEN others THEN
            -- Already NOT NULL on a fresh DB — no action needed.
            NULL;
        END;
    END IF;
END $$;

-- Add the P3b UNIQUE constraint on the upgraded schema. The CREATE TABLE
-- statement above declares it for fresh DBs; this DO block is the
-- equivalent for upgraded DBs where CREATE TABLE was a no-op.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'copy_targets_user_id_target_wallet_address_key'
    ) THEN
        BEGIN
            ALTER TABLE copy_targets
                ADD CONSTRAINT copy_targets_user_id_target_wallet_address_key
                UNIQUE (user_id, target_wallet_address);
        EXCEPTION WHEN duplicate_table OR unique_violation OR others THEN
            -- A duplicate row in legacy data would prevent the constraint
            -- from being added — operator must reconcile manually before
            -- re-running. Surface as a NOTICE rather than blocking the
            -- migration on every other concern.
            RAISE NOTICE 'copy_targets unique-add deferred: %', SQLERRM;
        END;
    END IF;
END $$;

-- Hot-path query: "list this user's active copy targets" (CopyTradeStrategy.scan).
CREATE INDEX IF NOT EXISTS idx_copy_targets_user_status
    ON copy_targets (user_id, status);

-- ---------------------------------------------------------------------------
-- copy_trade_events: append-only log of mirrored leader trades.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS copy_trade_events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    copy_target_id      UUID REFERENCES copy_targets(id) ON DELETE CASCADE,
    source_tx_hash      VARCHAR(66) NOT NULL,
    mirrored_order_id   UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Per-follower dedup: the same leader trade may be mirrored by every
    -- follower of the leader, but a single follower must not mirror the
    -- same leader trade twice. The unique composite index on
    -- (copy_target_id, source_tx_hash) is the dedup boundary; the prefix
    -- on copy_target_id also covers the "list a user's mirrored history"
    -- read pattern, so no extra index is needed.
    UNIQUE (copy_target_id, source_tx_hash)
);

CREATE INDEX IF NOT EXISTS idx_copy_trade_events_created_at
    ON copy_trade_events (copy_target_id, created_at DESC);
