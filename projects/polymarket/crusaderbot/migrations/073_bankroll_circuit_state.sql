-- Migration 073: bankroll circuit-breaker state persistence
-- WARP/ROOT/bankroll-cb-persistence-impl  (closes audit F19/F4)
--
-- Persists the per-user bankroll circuit-breaker baseline + tripped latch so
-- they survive a process restart / redeploy. Without this, the in-memory state
-- (_bankroll_ema_baseline / _bankroll_circuit_tripped in
-- services/signal_scan/signal_scan_job.py) resets on every restart — a TRIPPED
-- breaker would silently un-trip and the peak baseline would reset to the
-- current (possibly drawn-down) balance.
--
-- DARK: written/read only when BANKROLL_CIRCUIT_BREAKER_ENABLED=true (default
-- false), so this table is inert until the breaker is enabled via the directive
-- validate track. Deny-by-default RLS (no policy) keeps it backend-only; the
-- backend/bot use the service_role / postgres connection which bypasses RLS.

CREATE TABLE IF NOT EXISTS bankroll_circuit_state (
    user_id     UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    baseline    NUMERIC NOT NULL,
    tripped     BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE bankroll_circuit_state IS
    'Restart-durable per-user bankroll circuit-breaker state: peak baseline + tripped latch (WARP/ROOT/bankroll-cb-persistence-impl, audit F19/F4). Inert unless BANKROLL_CIRCUIT_BREAKER_ENABLED=true.';

-- Deny-by-default RLS: enable RLS, create NO policy. anon/authenticated have
-- no access; the backend's service_role / postgres role bypasses RLS.
ALTER TABLE bankroll_circuit_state ENABLE ROW LEVEL SECURITY;
