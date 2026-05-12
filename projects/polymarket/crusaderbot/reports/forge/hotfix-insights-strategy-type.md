# WARP•FORGE REPORT — hotfix-insights-strategy-type

Validation Tier: MINOR
Claim Level: NARROW INTEGRATION
Validation Target: jobs/weekly_insights.py signal breakdown query
Not in Scope: execution guards, business logic, schema, other modules
Suggested Next Step: WARP🔹CMD review — merge when ready

---

## 1. What was built

Surgical one-query fix in `jobs/weekly_insights.py`. The signal breakdown
query (line 60) referenced `strategy_type` directly from the `positions`
table, which does not have that column. `strategy_type` lives on `orders`.
The fix adds `LEFT JOIN orders o ON o.id = p.order_id` and qualifies the
column reference as `o.strategy_type`. All other column references in the
query are also table-aliased (`p.*`) for correctness.

Fixes Sentry issues: DAWN-SNOWFLAKE-1729-10, DAWN-SNOWFLAKE-1729-Z.

---

## 2. Current system architecture

No architectural change. `positions` is joined to `orders` at query time to
read `strategy_type`; this is the correct normalised path — `strategy_type`
was always intended to be read via the order relationship.

---

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/jobs/weekly_insights.py` — signal query
  LEFT JOIN orders, qualified column aliases (lines 59–79)

No files created. No migrations needed.

---

## 4. What is working

- `/insights` command and `weekly_insights` cron job will execute without
  `UndefinedColumnError`.
- Signal breakdown groups by `o.strategy_type` (NULL-safe via COALESCE to
  `'unknown'`).
- Positions without an associated order (order_id IS NULL) fall into the
  `'unknown'` signal bucket via LEFT JOIN semantics.
- Category breakdown query and summary query unchanged.

---

## 5. Known issues

None introduced. Root cause was a column reference on the wrong table — no
missing migration, no schema drift.

---

## 6. What is next

WARP🔹CMD review required. Tier: MINOR.
Source: projects/polymarket/crusaderbot/reports/forge/hotfix-insights-strategy-type.md
