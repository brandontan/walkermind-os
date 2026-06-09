-- migration 067 — global strategy on/off toggle (operator admin control)
--
-- Lane: WARP/ROOT-admin-page (MAJOR — touches scanner gate)
--
-- Adds a global `strategies` registry the operator can flip on/off from the
-- WebTrader Admin page. The signal scanner consults it as a FAIL-SAFE override:
-- a strategy runs UNLESS there is a row marking it enabled=FALSE. An empty /
-- missing row = enabled (no behaviour change), so this is additive and safe.
--
-- Seeded with every known strategy (lib + domain) at enabled=TRUE.

CREATE TABLE IF NOT EXISTS strategies (
    name        VARCHAR(64) PRIMARY KEY,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE strategies IS
  'Global per-strategy on/off switch (operator-controlled via WebTrader Admin). '
  'Scanner treats a strategy as ON unless a row here has enabled=FALSE '
  '(fail-safe: missing row = ON).';

INSERT INTO strategies (name, enabled) VALUES
    ('signal_following',  TRUE),
    ('late_entry_v3',     TRUE),
    ('confluence_scalper', TRUE),
    ('momentum_reversal', TRUE),
    ('copy_trade',        TRUE),
    ('trend_breakout',    TRUE),
    ('momentum',          TRUE),
    ('value_investor',    TRUE),
    ('expiration_timing', TRUE),
    ('pair_arb',          TRUE),
    ('ensemble',          TRUE),
    ('whale_tracking',    TRUE)
ON CONFLICT (name) DO NOTHING;

-- Deny-by-default RLS parity (migration 046 pattern): anon/authenticated locked
-- out; the backend reaches this via service_role / postgres owner (bypass RLS).
ALTER TABLE strategies ENABLE ROW LEVEL SECURITY;
