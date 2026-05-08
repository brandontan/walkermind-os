-- 014_add_is_demo_flag.sql
-- Lane 1C demo data isolation flag.
--
-- Adds an additive `is_demo BOOLEAN NOT NULL DEFAULT FALSE` column to every
-- table the demo seed script writes into. The column lets the cleanup
-- script delete demo rows in isolation without touching any production
-- record (`is_demo = FALSE` for every pre-existing row by virtue of the
-- DEFAULT FALSE backfill — Postgres rewrites the table on ALTER TABLE
-- ADD COLUMN with a non-volatile default, but the value applied to every
-- existing row is FALSE so no production data is modified semantically).
--
-- Tables flagged:
--   users                  - 2 demo users (telegram_user_id = -1, -2)
--   wallets                - paper balance for demo users
--   user_settings          - paper risk profile for demo users
--   signal_feeds           - 2 operator-curated demo feeds
--   signal_publications    - 8-12 demo signals across the feeds
--   user_signal_subscriptions - demo-user feed enrolments
--   markets                - demo markets the signals reference (avoids
--                             coupling demo to live Polymarket sync state)
--   orders                 - 7-day paper-trade history orders
--   positions              - 7-day paper-trade history positions
--   ledger                 - paper credits/debits backing daily_pnl reads
--
-- Idempotency: every ALTER TABLE is wrapped in a DO $$ block guarded by
-- pg_attribute lookup, so re-running the migration on a database that
-- already has the column is a no-op. Partial indexes use IF NOT EXISTS.
--
-- ROLLBACK: the symmetric DROP statements are documented at the bottom
-- of this file as a copy-paste block. The migration runner only applies
-- forward SQL; rollback is operator-executed via psql against a stopped
-- bot instance. The rollback block is also idempotent (DROP COLUMN IF
-- EXISTS / DROP INDEX IF EXISTS) so it survives partial application.

-- ---------------------------------------------------------------------------
-- Forward DDL
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    t TEXT;
    tables TEXT[] := ARRAY[
        'users',
        'wallets',
        'user_settings',
        'signal_feeds',
        'signal_publications',
        'user_signal_subscriptions',
        'markets',
        'orders',
        'positions',
        'ledger'
    ];
BEGIN
    FOREACH t IN ARRAY tables LOOP
        IF NOT EXISTS (
            SELECT 1
              FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name = t
               AND column_name = 'is_demo'
        ) THEN
            EXECUTE format(
                'ALTER TABLE %I ADD COLUMN is_demo BOOLEAN NOT NULL DEFAULT FALSE',
                t
            );
        END IF;
    END LOOP;
END
$$;

-- Partial indexes on the high-cardinality tables only. The seed never
-- inserts more than ~2 rows into users/wallets/user_settings/signal_feeds
-- so a partial index there is overhead without payoff. Cleanup scans by
-- is_demo on the four tables below and benefits from a covering index.
CREATE INDEX IF NOT EXISTS idx_signal_publications_is_demo
    ON signal_publications (is_demo) WHERE is_demo = TRUE;

CREATE INDEX IF NOT EXISTS idx_orders_is_demo
    ON orders (is_demo) WHERE is_demo = TRUE;

CREATE INDEX IF NOT EXISTS idx_positions_is_demo
    ON positions (is_demo) WHERE is_demo = TRUE;

CREATE INDEX IF NOT EXISTS idx_ledger_is_demo
    ON ledger (is_demo) WHERE is_demo = TRUE;

-- ---------------------------------------------------------------------------
-- ROLLBACK (operator-executed, NOT applied by the runner)
-- ---------------------------------------------------------------------------
--
-- Run the block below via psql to fully reverse this migration. Safe to
-- re-run because every DROP is guarded by IF EXISTS. Run after the
-- demo cleanup script has emptied is_demo=TRUE rows.
--
-- BEGIN;
-- DROP INDEX IF EXISTS idx_signal_publications_is_demo;
-- DROP INDEX IF EXISTS idx_orders_is_demo;
-- DROP INDEX IF EXISTS idx_positions_is_demo;
-- DROP INDEX IF EXISTS idx_ledger_is_demo;
-- ALTER TABLE users                     DROP COLUMN IF EXISTS is_demo;
-- ALTER TABLE wallets                   DROP COLUMN IF EXISTS is_demo;
-- ALTER TABLE user_settings             DROP COLUMN IF EXISTS is_demo;
-- ALTER TABLE signal_feeds              DROP COLUMN IF EXISTS is_demo;
-- ALTER TABLE signal_publications       DROP COLUMN IF EXISTS is_demo;
-- ALTER TABLE user_signal_subscriptions DROP COLUMN IF EXISTS is_demo;
-- ALTER TABLE markets                   DROP COLUMN IF EXISTS is_demo;
-- ALTER TABLE orders                    DROP COLUMN IF EXISTS is_demo;
-- ALTER TABLE positions                 DROP COLUMN IF EXISTS is_demo;
-- ALTER TABLE ledger                    DROP COLUMN IF EXISTS is_demo;
-- COMMIT;
