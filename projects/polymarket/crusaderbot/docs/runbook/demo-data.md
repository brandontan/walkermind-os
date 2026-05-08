# Demo Data Runbook — Lane 1C

CrusaderBot demo seed + cleanup procedures. The demo dataset is fully
isolated behind the `is_demo BOOLEAN` flag introduced by migration
`014_add_is_demo_flag.sql`. Every demo row carries `is_demo = TRUE`;
production rows keep the column DEFAULT FALSE. Cleanup deletes only
`is_demo = TRUE` rows — production data is never touched.

## When to use

* Before a live demo / investor walk-through where empty `/signals`,
  `/dashboard`, and `/pnl` surfaces would look broken.
* After a fresh staging deploy that has the migration applied but no
  organic activity yet.

Do **NOT** run on production unless you are deliberately seeding a
demo profile for an investor demo on the live bot. The seed script is
idempotent and safe, but the cleanup is your only revert path.

## Prerequisites

1. Migration `014_add_is_demo_flag.sql` applied (the bot does this on
   startup; verify with the column check below).
2. `DATABASE_URL` env var set in the shell that will run the script.
3. `OPERATOR_CHAT_ID` env var set — the seed resolves the boss user UUID
   from this Telegram ID and uses it as the operator on the two demo
   feeds.
4. The boss has run `/start` at least once on the bot so the operator
   user row exists.

Column check:

```sql
SELECT table_name
  FROM information_schema.columns
 WHERE table_schema = 'public'
   AND column_name = 'is_demo'
 ORDER BY table_name;
-- Expected: ledger, markets, orders, positions, signal_feeds,
-- signal_publications, user_settings, user_signal_subscriptions,
-- users, wallets
```

## What gets created

| Table                       | Demo rows |
|-----------------------------|-----------|
| `markets`                   | 12 (`demo-market-001` … `demo-market-012`) |
| `users`                     | 2  (`telegram_user_id` = -1, -2) |
| `wallets`                   | 2  (`balance_usdc = 10000.00`, address `0xDEMO…`) |
| `user_settings`             | 2  (`risk_profile = balanced`, `paper`) |
| `signal_feeds`              | 2  (`demo-politics-watcher`, `demo-sports-edge`) |
| `signal_publications`       | 10 (entry signals, last 12h) |
| `user_signal_subscriptions` | 3  (user1→Politics, user2→both) |
| `orders`                    | 32 (paper, 7-day spread) |
| `positions`                 | 32 (paper, all closed, 58% win) |
| `ledger`                    | 32 (`trade_close` rows) |

`access_tier` for both demo users is **3 (FUNDED)**. `auto_trade_on` is
**FALSE** so the execution loop will never pick them up.

The seed never modifies the kill-switch, never touches activation
guards (`ENABLE_LIVE_TRADING`, `EXECUTION_PATH_VALIDATED`, etc.), and
never inserts into `audit.log` or `system_settings`.

## Run the seed

```bash
DEMO_SEED_ALLOW=1 \
DATABASE_URL='postgresql://…' \
OPERATOR_CHAT_ID='<boss telegram id>' \
python -m projects.polymarket.crusaderbot.scripts.seed_demo_data
```

Exit codes:

| Code | Meaning |
|------|---------|
| 0    | seeded successfully (or already seeded — no-op) |
| 2    | `DEMO_SEED_ALLOW=1` missing — refused |
| 3    | prerequisite missing (migration not applied / no boss user) |
| 4    | database error |

The script is idempotent: re-running it inserts only rows that are not
already present. UUIDs are derived from a fixed namespace
(`uuid5(DEMO_NS, label)`) so every demo row has a stable identity
across runs.

## Verify the seed

After running:

```sql
-- 2 active demo feeds
SELECT slug, name, status, subscriber_count
  FROM signal_feeds WHERE is_demo = TRUE;

-- 10 entry publications spread across the last 12h
SELECT feed_id, COUNT(*) FROM signal_publications
 WHERE is_demo = TRUE GROUP BY feed_id;

-- /pnl numerator: today's trade_close ledger rows
SELECT user_id, COUNT(*), SUM(amount_usdc)
  FROM ledger
 WHERE is_demo = TRUE
   AND created_at >= date_trunc('day', NOW())
 GROUP BY user_id;
```

Telegram surface checks (run as boss or any allowlisted user):

* `/signals catalog` — both demo feeds appear.
* `/dashboard` for the demo users (or any user — the bot reads per-
  user state) — paper balance $10,000 and a non-zero today's P&L.
* `/about`, `/status`, `/demo` — unaffected (no schema overlap).

## Run the cleanup

```bash
DEMO_CLEANUP_CONFIRM=1 \
DATABASE_URL='postgresql://…' \
python -m projects.polymarket.crusaderbot.scripts.cleanup_demo_data
```

Exit codes:

| Code | Meaning |
|------|---------|
| 0    | cleaned successfully (or no demo rows present — no-op) |
| 2    | `DEMO_CLEANUP_CONFIRM=1` missing — refused |
| 3    | prerequisite missing (migration not applied) |
| 4    | database error |
| 5    | verification failed — demo rows survived (investigate) |

The cleanup runs all DELETE statements in a single transaction and
re-counts `is_demo = TRUE` rows after commit. A non-zero residual count
returns exit code 5 — do not assume cleanup succeeded if the script did
not log `Cleanup verified: 0 demo rows remain across all tables.`

## Rollback the migration (only after cleanup)

The migration file `014_add_is_demo_flag.sql` ships its rollback DDL as
an in-file comment block. Stop the bot, run the cleanup script, then
execute the block in psql:

```sql
BEGIN;
DROP INDEX IF EXISTS idx_signal_publications_is_demo;
DROP INDEX IF EXISTS idx_orders_is_demo;
DROP INDEX IF EXISTS idx_positions_is_demo;
DROP INDEX IF EXISTS idx_ledger_is_demo;
ALTER TABLE users                     DROP COLUMN IF EXISTS is_demo;
ALTER TABLE wallets                   DROP COLUMN IF EXISTS is_demo;
ALTER TABLE user_settings             DROP COLUMN IF EXISTS is_demo;
ALTER TABLE signal_feeds              DROP COLUMN IF EXISTS is_demo;
ALTER TABLE signal_publications       DROP COLUMN IF EXISTS is_demo;
ALTER TABLE user_signal_subscriptions DROP COLUMN IF EXISTS is_demo;
ALTER TABLE markets                   DROP COLUMN IF EXISTS is_demo;
ALTER TABLE orders                    DROP COLUMN IF EXISTS is_demo;
ALTER TABLE positions                 DROP COLUMN IF EXISTS is_demo;
ALTER TABLE ledger                    DROP COLUMN IF EXISTS is_demo;
COMMIT;
```

Every DROP is guarded by `IF EXISTS`, so the block is safe to run on
a database where the migration was only partially applied or where the
cleanup already removed the demo rows.

## Safety flags — why both

| Flag                       | Required by | Reason |
|----------------------------|-------------|--------|
| `DEMO_SEED_ALLOW=1`        | seed_demo_data.py | Forces the operator to opt in explicitly. Prevents an `apt-get` reflex of running a stray Python module from auto-seeding production. |
| `DEMO_CLEANUP_CONFIRM=1`   | cleanup_demo_data.py | Cleanup is destructive — even though it is scoped to `is_demo = TRUE`, an explicit confirm gate forces the operator to read the runbook before running. |

Both flags are checked at the very top of the script and the process
exits before opening a database connection if either guard is missing.
There is no code path that bypasses these checks.
