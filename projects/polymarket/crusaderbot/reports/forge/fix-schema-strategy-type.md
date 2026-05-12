# WARP•FORGE Report — fix-schema-strategy-type

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: orders.strategy_type column existence in live DB
Not in Scope: weekly_insights.py query logic, positions table, any execution path
Suggested Next Step: WARP🔹CMD review and merge

---

## 1. What was built

Idempotent `ALTER TABLE` migration that ensures `orders.strategy_type VARCHAR(50)` exists
in the production database. The column was already declared in `001_init.sql` CREATE TABLE
but was never back-filled via ALTER TABLE for databases provisioned before that column was
added to the init script. This caused `UndefinedColumnError` in `_fetch_weekly_stats()`
(Sentry DAWN-SNOWFLAKE-1729-10 and DAWN-SNOWFLAKE-1729-Z).

---

## 2. Current system architecture

Migration runner in `database.run_migrations()` globs all `*.sql` files from the
`migrations/` directory in sorted order and executes each in a single connection.
The new file `026_add_strategy_type_to_orders.sql` is picked up automatically on
next restart — no changes to `database.py` required.

---

## 3. Files created / modified

Created:
- `projects/polymarket/crusaderbot/migrations/026_add_strategy_type_to_orders.sql`

Modified: none

---

## 4. What is working

- Migration is idempotent: `ADD COLUMN IF NOT EXISTS` is a no-op when the column
  already exists (new deploys from clean `001_init.sql`).
- `_fetch_weekly_stats()` signal breakdown query (`weekly_insights.py:61–80`) joins
  `orders` on `o.strategy_type` — column will resolve after migration runs on next
  bot restart.
- `run_migrations()` picks up file via glob without any code change.

---

## 5. Known issues

None.

---

## 6. What is next

WARP🔹CMD review and merge. No WARP•SENTINEL required (STANDARD tier).
After merge, next bot deploy will run migration 026 and resolve the
`UndefinedColumnError` permanently.
