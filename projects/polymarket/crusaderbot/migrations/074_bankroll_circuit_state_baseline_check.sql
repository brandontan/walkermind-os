-- Migration 074: enforce baseline > 0 on bankroll_circuit_state
-- WARP/ROOT/bankroll-cb-persist-hardening
--
-- _restore_bankroll_circuit_state() already skips rows with baseline <= 0
-- at the application layer. This migration adds the matching DB constraint
-- so invalid state can never land in storage in the first place.
--
-- Safe to apply before or after enabling BANKROLL_CIRCUIT_BREAKER_ENABLED:
-- the table was created in migration 073 and is inert (dark) until the flag
-- is enabled, so no production rows exist yet. The DELETE below is a
-- defensive guard for any test/staging rows.

DELETE FROM bankroll_circuit_state WHERE baseline IS NULL OR baseline <= 0;

ALTER TABLE bankroll_circuit_state
    ADD CONSTRAINT bankroll_circuit_state_baseline_positive CHECK (baseline > 0);
