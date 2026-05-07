-- 011_execution_queue.sql
-- Phase 3d: execution queue for signal scan loop deduplication + observability.
--
-- Adds one table:
--   execution_queue   -- per-user, per-publication record of candidates that
--                        passed the risk gate and were submitted to the
--                        execution router.  The UNIQUE partial index on
--                        (user_id, publication_id) is the permanent dedup
--                        boundary: once a publication has been executed for a
--                        given user it will never be reprocessed, even across
--                        scan ticks separated by more than the 30-minute
--                        idempotency_keys window.
--
-- Status lifecycle:
--   queued     -> risk approved, INSERT succeeded, router_execute not yet called
--   executed   -> router_execute completed without raising
--   failed     -> router_execute raised; final_size_usdc / error_detail preserved
--
-- Idempotency: every CREATE uses IF NOT EXISTS.  Safe to re-run on startup.

CREATE TABLE IF NOT EXISTS execution_queue (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    strategy_name       VARCHAR(50) NOT NULL,
    market_id           VARCHAR(255) NOT NULL,
    side                VARCHAR(10) NOT NULL,
    publication_id      UUID,
    suggested_size_usdc NUMERIC(20, 6) NOT NULL DEFAULT 0,
    final_size_usdc     NUMERIC(20, 6),
    idempotency_key     VARCHAR(255) NOT NULL,
    chosen_mode         VARCHAR(10),
    status              VARCHAR(20) NOT NULL DEFAULT 'queued',
    error_detail        TEXT,
    queued_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    executed_at         TIMESTAMPTZ
);

-- Permanent per-user per-publication dedup: prevents re-execution of the
-- same signal_following publication across scan ticks.  Only applies when
-- publication_id is set (signal_following path); other strategies may omit
-- it and rely solely on the idempotency_keys window.
CREATE UNIQUE INDEX IF NOT EXISTS uq_exec_queue_user_pub
    ON execution_queue (user_id, publication_id)
    WHERE publication_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_execution_queue_status
    ON execution_queue (status, queued_at);

CREATE INDEX IF NOT EXISTS idx_execution_queue_user_strategy
    ON execution_queue (user_id, strategy_name, queued_at DESC);
