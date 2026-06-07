# WARP•FORGE Report — drop-job-runs-persistence

Branch: WARP/drop-job-runs-persistence
Role: WARP•R00T (system hardening follow-up to WARP-82)
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: the 3 operator readers (health / hourly_report / settings) now source job-run stats from the in-memory ring instead of the dropped job_runs table; migration 088 drops job_runs.
Not in Scope: trading/risk/execution paths; the in-memory ring write path (unchanged from WARP-82); running the migration (applies via CD release_command, not from CC); reinstating durable job history.
Suggested Next Step: WARP🔹CMD review → merge → confirm on the next CD deploy that 088 records in schema_migrations + job_runs is gone + /health renders live (non-zero, non-DOWN). Then drop the `_warp82_backup_*` tables once retention is confirmed unneeded.

## 1. What was built

A follow-up to WARP-82 that completes the job_runs decommission.

WARP-82 killed the job_runs **writer** (the APScheduler listener now routes
outcomes to an in-memory ring in `domain/ops/job_tracker.py`) but deliberately
kept the table because three operator surfaces still read it via raw SQL. With
the writer dead those readers were querying a **frozen** table, so the hour-window
figures decayed to stale/false values (e.g. `/health` "Markets scanned (1h)" → 0
and a false "Signal scan may be DOWN", hourly report "0 scans / Uptime 100%").

This lane repoints all three readers at the ring and drops the table:

- Added two bounded-ring aggregation helpers to `job_tracker`:
  `count_runs_since(since, *, job_id=None, only_failed=False)` and
  `distinct_jobs_since(since)`, mirroring the former
  `count(*) … WHERE started_at > $1` / `count(DISTINCT job_name)` queries.
- Bumped the ring `_RECENT_MAXLEN` 200 → 1000 so the hour-window aggregates that
  now back `/health` + the hourly report stay representative rather than
  truncated by high-frequency scheduler ticks.
- Repointed `health.py`, `hourly_report.py`, `settings.py` off `job_runs`.
  Removed a **dead** `total_jobs` query in `health.py` (it was computed but never
  used — the return dict hardcodes `total_jobs_distinct: 17`).
- Migration `088_drop_job_runs.sql` → `DROP TABLE IF EXISTS job_runs CASCADE;`.

## 2. Current system architecture

```
APScheduler job exec
  → _job_tracker_listener (scheduler.py)
  → job_tracker.record_job_event()  ── stdout (job.start/end/error) + Sentry-on-error
                                     └─ in-memory ring _recent_runs (deque, maxlen 1000)
                                            ▲
        ┌───────────────────────────────────┼───────────────────────────────────┐
   fetch_latest(job_id)           count_runs_since / distinct_jobs_since      fetch_recent(limit)
        │                                    │                                    │
   /health "last scan"        /health markets_1h/running_jobs/errors_1h    /settings recent jobs
                              hourly_report scans/total_jobs/error_jobs
```

No reader touches `job_runs` (table dropped). Signal/trade/PnL figures in
`/health` + hourly report still come from their own DB tables
(`signal_publications`, `orders`, `positions`) — unchanged.

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/migrations/088_drop_job_runs.sql`

Modified:
- `projects/polymarket/crusaderbot/domain/ops/job_tracker.py` — ring 200→1000; added `count_runs_since` + `distinct_jobs_since`.
- `projects/polymarket/crusaderbot/bot/handlers/health.py` — 4 job_runs queries → ring helpers; dropped dead `total_jobs` query; import `job_tracker`.
- `projects/polymarket/crusaderbot/jobs/hourly_report.py` — 3 job_runs queries → ring helpers; import `job_tracker`.
- `projects/polymarket/crusaderbot/bot/handlers/settings.py` — recent-jobs read → `job_tracker.fetch_recent`; import `job_tracker`; removed its pool acquire.
- `projects/polymarket/crusaderbot/tests/test_no_persistence_to_bloat_tables.py` — 088 drops job_runs assertion + `test_no_read_sites_to_job_runs` guard.
- `projects/polymarket/crusaderbot/tests/test_job_tracker.py` — 2 ring-aggregation tests.

## 4. What is working

- `pytest tests/test_job_tracker.py tests/test_no_persistence_to_bloat_tables.py` → 15 passed.
- `ruff check` clean on all touched files; `py_compile` clean on all 4 production modules.
- Read-site guard proves zero `FROM job_runs` SQL remains in production code.
- Ring aggregation verified: window filtering, `job_id` filter, `only_failed`
  (status `failed`), and distinct-name counting against a seeded ring.

## 5. Known issues

- The ring is **per-process and ephemeral** — restart/redeploy resets it, so the
  first hour-window after a deploy under-reports (counts only post-restart runs).
  This is strictly better than the pre-fix frozen-table behaviour and is
  acceptable for operator observability (the staleness flag keys off
  `fetch_latest`, not the counts). Durable cross-restart job history is gone by
  design (operator ruling: real-time data needs no durable storage).
- Hour-window counts are a **lower bound** if executions in the window exceed the
  ring size (1000) — not expected at current cadences.
- Migration 088 has **not** run yet from CC by design — it applies on the next CD
  deploy via the `release_command`. Until then `/health` etc. already read the
  ring (deploy-independent); the table simply lingers empty until dropped.

## 6. What is next

- WARP🔹CMD review → merge.
- On the next CD deploy: confirm `schema_migrations` records `088`, `job_runs` is
  dropped, and `/health` renders live values.
- Optional cleanup: drop the `_warp82_backup_*` tables once retention is confirmed
  unneeded (job_runs backup = `_warp82_backup_job_runs`, 835 rows).
