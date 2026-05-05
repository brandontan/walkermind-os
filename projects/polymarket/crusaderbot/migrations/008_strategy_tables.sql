-- 008_strategy_tables.sql
-- Phase 3a foundation: strategy registry persistence layer.
--
-- Adds three tables that back the pluggable strategy plane:
--   strategy_definitions  — operator-managed catalog of strategies the
--                           StrategyRegistry can load.
--   user_strategies       — per-user strategy enrolment with weight, enabled
--                           flag, and free-form params.
--   user_risk_profile     — per-user risk profile selection with optional
--                           custom override JSON.
--
-- Idempotency: every CREATE TABLE uses IF NOT EXISTS. The migration is safe
-- to re-run on every startup (the migration runner re-executes 0xx files on
-- boot — see existing 004_deposit_log_index.sql for the pattern).
--
-- Foundation only: no execution path, no risk logic, no signal generation
-- consume these tables yet. Phase 3b/c lanes wire them in.

-- ---------------------------------------------------------------------------
-- strategy_definitions: operator-managed strategy catalog.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS strategy_definitions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(50) UNIQUE NOT NULL,
    version       VARCHAR(20) NOT NULL,
    params_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    status        VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- user_strategies: per-user enrolment in registered strategies.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_strategies (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    strategy_name VARCHAR(50) NOT NULL,
    weight        DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    params_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, strategy_name)
);

CREATE INDEX IF NOT EXISTS idx_user_strategies_user_enabled
    ON user_strategies (user_id, enabled);

-- ---------------------------------------------------------------------------
-- user_risk_profile: per-user risk profile selection.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_risk_profile (
    user_id          UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    profile_name     VARCHAR(20) NOT NULL DEFAULT 'balanced',
    custom_overrides JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
