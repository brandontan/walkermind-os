-- Migration 042: Drop legacy sessions table
-- The sessions table was created in 001_init.sql as a planned auth session store.
-- WebTrader uses stateless JWT (WEBTRADER_JWT_SECRET) — no rows are written to this table.
-- Safe to drop: zero Python references to INSERT/SELECT from sessions.

DROP TABLE IF EXISTS sessions;

-- NOTE: copy_targets is NOT dropped here.
-- Active Python references remain in:
--   bot/handlers/copy_trade.py (legacy dispatcher)
--   bot/handlers/setup.py (add/remove target wallet)
--   domain/signal/copy_trade.py (enabled targets query)
-- Cleanup of copy_targets requires a coordinated Python removal lane first.
