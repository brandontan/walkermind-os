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
