# WARP-82 — Kill realtime persistence + disk safeguards (post-incident)

Validation Tier: **MAJOR**
Claim Level: **SYSTEM REFACTOR**
Validation Target: prod after merge + 24h observation (DB stays flat; operator
surfaces + Sharp Money degrade gracefully; disk-monitor alerts fire on threshold)
Suggested Next: WARP🔹CMD review + operator merge approval + post-merge 24h watch

---

## 1. Why

P0 incident (~8h downtime, closed 2026-06-07 09:51 UTC): four unbounded
log/snapshot tables filled the Supabase Free-tier 500 MB quota
(`market_snapshots` 718 MB, `heisenberg_realtime_trades` 352 MB, `risk_log`
154 MB, `job_runs` 71 MB) → Supabase set `default_transaction_read_only=on` at
the PG level → `001_init.sql` `CREATE EXTENSION` failed at boot →
`run_migrations` raised in the unwrapped lifespan → uvicorn boot loop. (Recovered
by truncating the 4 + applying mig 086 once read-only was lifted via dashboard
upgrade.)

Operator architectural ruling (Mr. Walker): **"Sinyal real-time gk perlu simpan
ke database"** — real-time signal/log streams must NOT have durable storage.
Retention/caps were explicitly rejected (they only delay recurrence). This lane
**removes the write paths** + **drops the tables** + adds a **disk safeguard**.

## 2. What changed

**Phase 0 audit (write/read sites):**

| table | writer (killed) | production readers (handled) |
|---|---|---|
| market_snapshots | `domain/research/snapshots.py:record_market_snapshots` | `domain/research/replay.py`, `domain/research/late_entry_oos.py` (research CLI, fail-soft on empty) |
| heisenberg_realtime_trades | `jobs/heisenberg_realtime_sync.py:run_job` | `domain/playbook/sharp_flow.py` (Sharp Money — already fail-soft `{}`), `services/copy_trade/realtime_fast_track.py` |
| risk_log | `domain/risk/gate.py:_log` | none (write-only) |
| job_runs | `domain/ops/job_tracker.py:record_job_event` | `job_tracker.fetch_*` (now in-memory), `jobs/hourly_report.py`, `bot/handlers/health.py`, `bot/handlers/settings.py` |

**Phase 1 — write sites killed (no DB):**
- `job_tracker`: `record_job_event` → `job.start/end/error` structured stdout +
  `sentry_sdk.capture_message` on error + a bounded **in-memory ring** (200);
  `fetch_latest/fetch_recent` read the ring so the operator `/panel` keeps working
  without durable storage. The `get_pool` import is gone.
- `risk_log` (`gate._log`): severity-gated — rejection → `sentry capture_message`
  (level=warning) + WARNING stdout; approval → info stdout. No DB.
- `heisenberg_realtime_sync.run_job`: fetch + `logger.debug` per trade; the UPSERT
  + retention prune are removed. **Consequence (intentional, flagged): the durable
  buffer fed Playbook Sharp Money + copy-trade fast-track; with no buffer
  `sharp_flow` returns no flow (fail-soft) → Sharp Money abstains.** Accepted
  trade-off of killing real-time persistence.
- `market_snapshots` (`snapshots.record_market_snapshots`): no-op (returns 0,
  debug log only); the raw universe stays in-memory in the scanner cycle.

**Phase 2 — migration 087** (`087_drop_realtime_persistence_tables.sql`,
idempotent `DROP TABLE IF EXISTS … CASCADE`): drops `market_snapshots`,
`heisenberg_realtime_trades`, `risk_log`. **`job_runs` is intentionally NOT
dropped yet** — its writer is killed (frozen, tiny) but three operator surfaces
still read it via raw SQL; its drop is a small follow-up once they are repointed
to the in-memory ring (dropping now would error those queries). CASCADE is safe:
the only inbound FK is `risk_log.user_id → users.id` (outbound from risk_log); no
retained table has an FK INTO the dropped three.

**Phase 3 — disk monitor** (`jobs/disk_monitor.py`, registered in `scheduler.py`
at a 5-min interval): queries `pg_database_size`; writes a `system_alerts` row at
**350 MB (warning)** / **425 MB (critical)** of the 500 MB cap; 1-hour
same-severity throttle; pure asyncio; every error is `logger.exception` +
`sentry_sdk.capture_exception` and swallowed (never crashes the scheduler).
Adapted to the real `system_alerts` schema (`severity/title/body/metadata` — no
`alert_type`/`message` column; the `disk_usage` discriminator lives in `metadata`).

**Phase 4 — tests** (42 pass): `test_no_persistence_to_bloat_tables.py`
(source-scan proves zero `INSERT INTO`/`UPDATE` to the 4 tables in production
code + 087 drops the 3), `test_disk_monitor.py` (no-alert/warn/critical/throttle/
fail-soft), and rewritten `test_job_tracker.py` / `test_heisenberg_realtime_trades.py`
/ `test_research_snapshots.py` asserting the new no-persistence behavior.

## 3. Validation

- 42/42 affected tests pass; `ruff` + `py_compile` clean; `system_alerts` INSERT
  shape verified against the live schema.
- Phase-0 grep: writer-site count = 1 per table (all killed); reader-site count
  handled (in-memory / fail-soft / research); migration-site count = 1 (mig 087).
- **Pre-cleanup backup taken** into `_warp82_backup_<table>` (heisenberg 3697,
  job_runs 835, risk_log 90, market_snapshots 0) before any drop.
- Migration 087 applies to prod via the normal CD deploy path (NOT run from CC,
  per scope lock).
- Fly HTTP `/health` (`api/health.py`) does NOT read any of these tables → no
  restart-loop risk from the drops.

## 4. Out of scope

- The migration runner hardening (`WARP/migration-runner-rca-and-fix` #1676 +
  `WARP/migrate-resilience` #1677) — separate merged lanes.
- Dropping `job_runs` + repointing its 3 operator readers to the in-memory ring —
  small follow-up (the table is frozen/tiny meanwhile).
- Re-architecting Sharp Money / copy-trade onto a non-durable in-memory flow cache
  (if those signals are wanted back without durable storage) — separate lane.

---

Validation Handoff (NEXT PRIORITY):

```
WARP🔹CMD review + operator merge approval; post-merge 24h observation.
Source: projects/polymarket/crusaderbot/reports/forge/warp-82-kill-realtime-persistence.md
Tier: MAJOR
```
