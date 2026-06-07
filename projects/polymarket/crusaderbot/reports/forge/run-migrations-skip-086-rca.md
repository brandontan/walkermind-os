# WARP-80 RCA — run_migrations skipped migration 086 (+ crash-looped boot)

Role: WARP•R00T (root-cause + hardening)
Validation Tier: **MAJOR** (boot path / infra / deploy wiring)
Claim Level: **NARROW INTEGRATION** (runner refactor + release-phase wiring; unit-tested.
The exact prod boot exception still needs `flyctl logs -a crusaderbot` to confirm — no log access from CC.)
Validation Target: why `run_migrations` did not apply migration 086 after the deploy, and a fix so it cannot recur.
Not in Scope: the 086 SQL (frozen, idempotent — verified); applying 086 to prod (no write path from CC → CMD dashboard); historical migration order.
Suggested Next Step: CMD applies 086 via dashboard (un-sticks the loop if 086 was the crash point) + shares Fly boot logs; then redeploy picks up the release-phase runner.

---

## Root cause (one line)

`run_migrations()` ran **inside the request-serving boot path, unwrapped, with no
tracking table** — so when the 086 deploy's boot hit a migration error it
**crash-looped the web app before 086 committed**, and Fly's `strategy='immediate'`
let CD still report "success". (Exact failing statement pending Fly logs; the
deploy/boot architecture is the systemic cause and is what this lane fixes.)

## Evidence

- `strategy_scan_observations` (086) **absent** in prod; migrations **080–085 applied** (Supabase MCP, project `ykyagjdeqcgcktnpdhes`).
- **No migration tracking table** existed (`schema_migrations` / `applied_migrations` / `migrations` → none) — confirms the runner re-ran all files every boot by idempotency convention only.
- `database.py` (pre-fix) `run_migrations`: `sorted(migrations_dir.glob("*.sql"))`, runs **every** file each call, **`raise`s on the first error** (aborting the rest); 086 sorts last so any earlier failure — or a failure on 086 itself — leaves 086 unapplied.
- `main.py:76`: `await run_migrations()` is **not wrapped** — a raise fails the FastAPI lifespan → uvicorn startup fails → the machine never becomes healthy.
- `fly.toml`: `[deploy] strategy = 'immediate'` (no `release_command`) → `flyctl deploy` does **not** gate on `/health`, so CD reported **success** for the 086 image (`fa336c0`/`a65e5e2`/`702aae0`) even though the app did not come up.
- Live prod at diagnosis time: `/health` → **503**, `/ready` + `/metrics` → **60s timeout** → the serving process is not healthy (crash-loop), consistent with a boot-time `run_migrations` failure.

Putting it together: the boot fails **at or before `run_migrations` completes** on the 086 image (080–085 already applied on prior healthy boots and are idempotent), so 086 never commits **and** prod goes down — while `immediate` masks it as a green deploy.

## What was fixed (this lane)

1. **Migration tracking table** (`schema_migrations`: `filename` PK, `checksum`, `applied_at`), created in-code (`CREATE TABLE IF NOT EXISTS`) by the runner. The runner now applies **only files not yet recorded**, records each on success, and **skips** already-applied ones — so a later file can never be blocked by re-running earlier ones, and **operators can query the DB to see exactly what ran** (the table CMD looked for and did not find). A checksum drift on an applied file is **WARNED, not silently re-run** (migrations are append-only).
2. **Decoupled migrations from the serving boot path** — added `fly.toml [deploy] release_command = 'python -m crusaderbot.scripts.migrate'` (`scripts/migrate.py`). Migrations now run in a **one-off release machine before promotion**: on failure the **deploy fails and Fly keeps the previous version serving**, instead of crash-looping the web app. The lifespan still calls `run_migrations`, but with the tracker that is a fast **skip-all** once the release step has applied everything (belt-and-suspenders for the non-release/worker path).
3. **Per-file fail-loud** preserved (logs the offending filename + re-raises) so a real error fails the deploy loudly rather than silently; files applied before a failure stay recorded so the next run resumes.
4. Refactored into testable units (`_discover_migrations`, `_load_applied_migrations`, `_apply_pending_migrations`, `run_migrations(*, migrations_dir, pool)`).

Each migration still **autocommits** (no outer transaction) — unchanged from the historical runner so statements that cannot run in a transaction (enum `ADD VALUE`, `CREATE INDEX CONCURRENTLY`) keep working. Application **order is unchanged** (sorted by filename).

## Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/database.py` — tracked, testable `run_migrations` + helpers (`hashlib` import)
- `projects/polymarket/crusaderbot/fly.toml` — `[deploy] release_command`
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `projects/polymarket/crusaderbot/state/CHANGELOG.md` — synced

Created:
- `projects/polymarket/crusaderbot/scripts/migrate.py` — release-phase migration entrypoint (non-zero exit on failure)
- `projects/polymarket/crusaderbot/tests/test_run_migrations.py` — 8 hermetic tests
- `projects/polymarket/crusaderbot/reports/forge/run-migrations-skip-086-rca.md` — this report

## What is working

- 8/8 hermetic tests pass (discovery sorted/sql-only, checksum determinism, apply-all-on-empty, skip-applied, **fail-loud + records prior**, **checksum-mismatch warn-not-rerun**, no-files, rerun-noop). `ruff` + `py_compile` clean; `fly.toml` parses.

## Known issues / caveats

- **086 still needs applying to prod** — no write path from CC (Supabase MCP read-only; no `DATABASE_URL`; no `flyctl`). CMD applies the frozen DDL via the Supabase dashboard. If the boot crash was *on 086*, that also un-sticks the loop (CREATE IF NOT EXISTS → no-op next boot).
- **Exact boot exception unconfirmed** — needs `flyctl logs -a crusaderbot`. If the crash is NOT a migration (e.g. a boot-time import error), applying 086 + this runner fix will not restore the app and the logs are required.
- `release_command` is **untestable from CC** (no Fly) — validated by TOML parse + the `python -m crusaderbot.scripts.migrate` path matching the Docker image layout (`crusaderbot` package, `scripts/__init__.py` present). First real exercise is the next deploy.
- First run of the new runner on prod finds an empty tracker → re-applies 080–086 idempotently (same as today's every-boot behavior) + records them; thereafter skip-all.

## What is next

1. CMD: apply 086 (dashboard) + share Fly boot logs.
2. Redeploy → release_command applies/records all migrations; app boots healthy; lifespan run_migrations becomes skip-all.
3. Step 4 verify (read-only via MCP): table/columns/indexes/RLS, then `SELECT count(*)` + `GROUP BY strategy` (weather + playbook rows within ~10–15 min).

---

Validation Handoff (NEXT PRIORITY):

```
WARP🔹CMD: apply 086 (dashboard) + share flyctl logs; review MAJOR boot-path change before merge.
Source: projects/polymarket/crusaderbot/reports/forge/run-migrations-skip-086-rca.md
Tier: MAJOR
```
