-- migration 071 — copy_trade_tasks.last_realtime_seen_at watermark
--
-- Lane: WARP/ROOT/copy-trade-realtime-fast-track (STANDARD / NARROW INTEGRATION)
--
-- Per-task high-water mark for the new fast-track consumer that reads from
-- the heisenberg_realtime_trades buffer (populated by agent 556 every 60s).
-- Without this, the fast-track would re-scan the full 24h buffer every tick.
--
-- NULL means: never run before — the consumer treats NULL as
-- "NOW() - 5 minutes" lookback so the first tick post-flip catches recent
-- trades without flooding.
--
-- Additive, idempotent. No data backfill needed. Existing leader-path
-- (services/copy_trade/wallet_watcher.py via the 30s monitor) is untouched.

ALTER TABLE copy_trade_tasks
    ADD COLUMN IF NOT EXISTS last_realtime_seen_at TIMESTAMPTZ;

COMMENT ON COLUMN copy_trade_tasks.last_realtime_seen_at IS
    'High-water mark for the fast-track consumer (services/copy_trade/realtime_fast_track.py). '
    'NULL = never run; consumer uses NOW() - 5min as the initial cutoff.';
