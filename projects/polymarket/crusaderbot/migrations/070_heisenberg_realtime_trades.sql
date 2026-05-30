-- migration 070 — Heisenberg agent 556 (real-time trades) buffer
--
-- Lane: WARP/ROOT/heisenberg-556-realtime-trades (STANDARD / FOUNDATION)
--
-- Buffers per-wallet fresh trades pulled from Heisenberg agent 556 so a future
-- copy-trade consumer lane can react with sub-minute latency instead of
-- waiting for the 30-minute leaderboard cycle (agent 584). The buffer is
-- additive — no existing copy-trade code reads from it yet; that wiring ships
-- in a follow-up lane once field-name assumptions have been confirmed against
-- production responses.
--
-- The job that populates this table (`jobs/heisenberg_realtime_sync.py`) is
-- triple-gated:
--   1. HEISENBERG_API_TOKEN set in env (shared with 574/575/568/585/584/581)
--   2. HEISENBERG_REALTIME_TRADES_ENABLED=True in config (DEFAULT FALSE)
--   3. Scheduler registers the job only when (2) is on.
--
-- Deny-by-default RLS parity (matches every other public table since mig 046).

CREATE TABLE IF NOT EXISTS heisenberg_realtime_trades (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet            VARCHAR(42) NOT NULL,
    condition_id      VARCHAR(80) NOT NULL,
    side              VARCHAR(8)  NOT NULL,            -- 'YES' / 'NO' (or 'BUY' / 'SELL' if upstream uses orderbook side)
    price             NUMERIC(8,5),                    -- normalised to [0, 1]; nullable in case upstream omits
    size_usdc         NUMERIC(18,6),                   -- nullable: upstream may report shares instead of USDC
    trade_time        TIMESTAMPTZ NOT NULL,            -- wall-clock time the trade happened upstream
    raw               JSONB,                           -- full raw payload for forensic debugging
    fetched_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Dedup key: agent 556 may return the same trade multiple times across windows.
-- We cannot rely on an upstream trade-id without confirming the field name, so
-- the (wallet, condition_id, trade_time, side) tuple is the de-facto unique
-- identifier — a wallet doesn't realistically place two identical-direction
-- trades on the same market in the same millisecond.
CREATE UNIQUE INDEX IF NOT EXISTS uq_hb_rt_trades_dedup
    ON heisenberg_realtime_trades (wallet, condition_id, trade_time, side);

-- Reverse-time wallet lookup powers a future copy-trade fast-track consumer:
-- "give me every fresh trade from these N target wallets in the last 5 min".
CREATE INDEX IF NOT EXISTS idx_hb_rt_trades_wallet_time
    ON heisenberg_realtime_trades (wallet, trade_time DESC);

-- Retention sweep index — the job DELETEs rows older than
-- HEISENBERG_REALTIME_TRADES_RETENTION_HOURS (default 24h) per tick.
CREATE INDEX IF NOT EXISTS idx_hb_rt_trades_fetched_at
    ON heisenberg_realtime_trades (fetched_at);

COMMENT ON TABLE heisenberg_realtime_trades IS
    'Buffer for Heisenberg agent 556 (real-time trades) — populated by '
    'jobs/heisenberg_realtime_sync.py. Future copy-trade fast-track consumer '
    'reads this table instead of waiting for the 30-minute leaderboard cycle.';

-- RLS: deny-by-default. The job writes via the postgres / service_role owner
-- which bypasses RLS; anon + authenticated have zero access. No policy created
-- — that's the deny-by-default design (matches strategies / account_link_codes
-- and every other table since migration 046).
ALTER TABLE heisenberg_realtime_trades ENABLE ROW LEVEL SECURITY;
