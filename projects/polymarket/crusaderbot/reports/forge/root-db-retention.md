# WARP•R00T — DB Retention (operational-table self-limiting)

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: a daily retention job that prunes the unbounded operational
time-series tables beyond generous per-table windows, so the DB self-limits and a
WARP-82-style disk-full read-only P0 cannot recur from slow operational growth.
Not in Scope: pruning `audit.log` (compliance trail — owner-governed) or any core
trading / FK-entangled table (positions, orders, ledger, fills, fees, markets,
factor_vectors); changing disk_monitor.
Suggested Next Step: ships on the next deploy; first run at 04:00 prunes the
~3,180 already-expired idempotency_keys and any rows beyond window. Owner to decide
`audit.log` retention separately.

---

## 1. What was built

Root-cause hardening for the owner directive *"pastikan tidak terjadi DB full
seperti sebelumnya."* WARP-82 fixed the **acute** disk-full cause (the realtime
bloat tables — dropped). The **remaining** risk is structural: ordinary
operational time-series tables have NO TTL and grow forever, and `disk_monitor`
only *alerts* at the 500 MB cap — it never frees space. This adds the missing
retention layer.

Audit of current DB (Supabase `ykyagjdeqcgcktnpdhes`, total **65 MB** — healthy):
no bloat tables remain, but these grow unbounded with no prune job —

| Table | rows | ~rows/day | retention added |
|---|---|---|---|
| portfolio_snapshots | 10,802 | ~1,766 | 90 days |
| system_alerts | 6,415 | ~677 | 30 days |
| scan_runs | 5,034 | ~431 | 30 days |
| execution_queue | 3,191 | ~337 | 30 days (executed rows only) |
| idempotency_keys | 3,191 | ~341 | expired (`expires_at < NOW()`) — 3,183 already dead |

New `jobs/db_retention.py` (`run_job`, `JOB_ID="db_retention"`), scheduled daily at
04:00 via the existing AsyncIOScheduler. Mirrors `jobs/disk_monitor.py`: pure
asyncio (no threading), fail-soft **per table** (one table erroring is logged +
Sentry'd and swallowed; the rest still prune; the scheduler never crashes), bounded
batched DELETE (`ctid` slices of 5,000, capped iterations) so a large backlog can't
hold a long table lock, and idempotent (re-running only deletes what is now beyond
window). Windows are config-driven and env-overridable; `DB_RETENTION_ENABLED`
(default ON) gates the whole job.

Deliberately **not** auto-pruned: `audit.log` (compliance audit trail, 8.6 MB —
flagged for owner-set retention) and all core trading / FK-entangled tables.

## 2. Current system architecture

```
AsyncIOScheduler
  ├─ disk_monitor   (5-min)  → ALERTS at 350/425 MB   (early warning, no free)
  └─ db_retention   (daily 04:00) → PRUNES beyond window  (frees space)  ← NEW
        per table, fail-soft:
          DELETE FROM <t> WHERE ctid = ANY(ARRAY(SELECT ctid FROM <t>
                 WHERE <window> LIMIT 5000))   -- looped until < batch
```

The two compose: retention keeps the DB small in normal operation; disk_monitor
remains the backstop alarm if anything unexpected still grows.

## 3. Files created / modified

- Created: `projects/polymarket/crusaderbot/jobs/db_retention.py`
- Created: `projects/polymarket/crusaderbot/tests/test_db_retention.py`
- Modified: `projects/polymarket/crusaderbot/config.py` (DB_RETENTION_* settings)
- Modified: `projects/polymarket/crusaderbot/scheduler.py` (register daily job)
- Created: `projects/polymarket/crusaderbot/reports/forge/root-db-retention.md`
- Modified: `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- Modified: `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- 8/8 hermetic tests pass (`tests/test_db_retention.py`): all five target tables
  pruned; disabled-flag no-op; idempotency_keys keys off `expires_at` (no day
  param); execution_queue only touches `executed_at IS NOT NULL` (never in-flight);
  day window bound as `$1`; **fail-soft** (a failing table does not abort the rest);
  batched loop continues until a sub-batch; pool-unavailable no-op. ruff +
  py_compile clean.
- Safety properties: only append-only operational tables; generous windows well
  clear of any read path (`portfolio_snapshots` has no code read with a lookback;
  charts keep 90 days); core/audit tables excluded; batched deletes bound lock time.

## 5. Known issues

- Windows are first-pass generous defaults; can be tuned via env if any chart needs
  longer history (none identified).
- `audit.log` (8.6 MB) intentionally untouched — needs an owner retention decision
  (compliance). Not a near-term disk risk.
- `markets` (30k rows / 21 MB) is the largest table and grows with Polymarket's
  short-lived updown markets; it is FK-referenced by positions/factor_vectors so it
  is NOT auto-pruned here. If it becomes a concern, a separate FK-aware prune
  (only fully-resolved markets with no referencing rows) is the follow-up.

## 6. What is next

- Deploy → first 04:00 run prunes the expired idempotency_keys + any beyond-window
  rows; verify deleted counts in logs / `db_retention` log lines.
- Owner: decide `audit.log` retention.
- Optional follow-up: FK-aware `markets` prune if that table's growth becomes
  material.
