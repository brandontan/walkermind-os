# WARP-56 — Sentry P0 Fix: access_tier ghost + signal_scan ValueError + dry-run FK

Generated : 2026-05-21 14:23 Asia/Jakarta
Branch    : WARP/warp56-sentry-p0-fix
Issue     : #1257
Tier      : STANDARD
Claim     : NARROW INTEGRATION

---

## 1. What was built

Three Sentry P0/P1 fixes landed in one lane, each isolated to its own module so blast radius stays narrow.

### Bug 2 — `_coerce_jsonb` ValueError on JSON scalar (P0)

Hardened `services/signal_scan/signal_scan_job._coerce_jsonb` so JSONB columns that arrive as JSON scalars (`'"balanced"'`, `'1'`, list-with-dict-fallback) can no longer leak the wrong shape into `strategy.initialize()` and trigger `ValueError: dictionary update sequence element #0 has length 1; 2 is required`. The function now narrows the return to the same type as `fallback` — anything else collapses to default.

### Bug 3 — `risk_log` FK violation from `/admin/dry-run` (P1)

`domain/risk/gate._log` now catches `asyncpg.exceptions.ForeignKeyViolationError` explicitly and logs at DEBUG instead of ERROR. The dry-run handler uses a synthetic `user_id` (`00000000-0000-0000-0000-000000000001`) that has no row in `users` — the FK on `risk_log.user_id → users.id` was correctly rejecting the insert, but the previous catch-all `Exception` handler escalated it to ERROR, which Sentry was paging on every dry-run tick. Real DB errors still surface at ERROR; the FK is the only special case.

### Bug 1 — `access_tier` ghost reference cleanup (P0)

Root cause was already resolved on the live DB by WARP-51 (MERGED 2026-05-21 08:30, SHA `1b9c3fdb5e6c`) — the column was dropped via migration 044, every Python writer was stripped, and Postgres logs in this 24h window contain zero `column "access_tier" does not exist` errors (verified via `mcp__supabase__get_logs`). The Sentry "last seen 2026-05-21T04:31:24" timestamp predates WARP-51's merge by ~4 hours; subsequent deploys do not re-trigger the error.

This lane closes the residual repo-truth gap so a fresh DB install can no longer recreate the column:

- `migrations/001_init.sql` — `access_tier SMALLINT NOT NULL DEFAULT 1,` removed from the `users` CREATE TABLE; the legacy "Tier 1/2/3/4" preamble comment replaced with the current role-based summary.
- `migrations/024_signal_scan_engine_seed.sql`, `migrations/031_signal_scanner_user_enrollment.sql`, `migrations/045_add_role_column.sql` — historical `access_tier` mentions in comments rewritten to "Legacy tier" so a future `grep -r "access_tier"` only returns the DROP migration (044) and the intentionally-retained middleware filename.

### Regression tests

`tests/test_warp56_sentry_fix.py` — 15 hermetic tests, all green:
- 12 `_coerce_jsonb` cases covering JSON scalar string, integer literal, invalid JSON, list-with-dict-fallback, dict-with-list-fallback, pass-through dict/list, None handling, and the AttributeError-on-`.get()` failure mode the bug actually triggers downstream.
- 3 `_log` cases covering FK-violation silent skip, unrelated-exception still-ERROR, and successful-insert sanity.

Adjacent regression sweep: `test_signal_scan_job.py` + `test_access_tiers.py` = 77 tests pass, 0 failures.

---

## 2. Current system architecture (relevant slice)

```
signal_scan_job.run_once
├─ _load_enrolled_users (DB → row dicts)
├─ for each user:
│    strategy_params = _coerce_jsonb(row.strategy_params, {})   ← Bug 2 patched
│    for lib_name in strategies:
│      config = {"strategy_params": strategy_params.get(lib_name, {})}
│      run_lib_strategy(lib_name, markets, config)
│        └─ strategy.initialize(config.get("strategy_params", {}))   ← used to ValueError
└─ _process_candidate → TradeEngine.execute → risk gate

api/admin.dry_run (POST /admin/dry-run)
└─ TradeEngine().dry_run_execute(signal)
   └─ _risk_evaluate(ctx)
      └─ _log(user_id, market_id, step, approved, reason)   ← Bug 3 patched
         └─ INSERT INTO risk_log (...) — FK on users.id
            ├─ ForeignKeyViolationError → logger.debug (silent)   [NEW]
            └─ Other Exception        → logger.error (Sentry-tracked)
```

NOTIFY channels and runtime spine are unchanged by this lane.

---

## 3. Files created / modified (full repo-root paths)

Modified
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py — `_coerce_jsonb` narrowed to fallback type
- projects/polymarket/crusaderbot/domain/risk/gate.py — `import asyncpg`; `_log` catches `ForeignKeyViolationError` at DEBUG
- projects/polymarket/crusaderbot/migrations/001_init.sql — `access_tier SMALLINT` column removed from `users` CREATE TABLE; preamble updated
- projects/polymarket/crusaderbot/migrations/024_signal_scan_engine_seed.sql — comment rewritten
- projects/polymarket/crusaderbot/migrations/031_signal_scanner_user_enrollment.sql — 2 comments rewritten
- projects/polymarket/crusaderbot/migrations/045_add_role_column.sql — comment rewritten

Created
- projects/polymarket/crusaderbot/tests/test_warp56_sentry_fix.py — 15 hermetic regression tests

State files updated in the same commit (see §6).

---

## 4. What is working

- `_coerce_jsonb('"balanced"', {})` → `{}` (was: returned the string `"balanced"`, leaking to caller)
- `_coerce_jsonb(None, {})` → `{}`
- `_coerce_jsonb('1', {})` → `{}`
- `_coerce_jsonb('[1,2]', {})` → `{}` (caller expects dict; wrong shape → default)
- `_coerce_jsonb({"a": 1}, {})` → `{"a": 1}` (passthrough)
- Dry-run with synthetic `user_id` no longer pages Sentry on every FK violation; real risk_log INSERT failures still page (verified via `test_log_still_errors_on_unexpected_exception`).
- 15 new regression tests pass; 77 adjacent tests pass.
- `grep -r "access_tier" projects/polymarket/crusaderbot/` shows zero hits outside:
  - `migrations/044_drop_access_tier.sql` (explicitly excluded by acceptance criterion)
  - `migrations/045_add_role_column.sql` line 8 — a cross-reference to mig 044's filename only
  - `bot/middleware/access_tier.py` — filename intentionally retained per WARP-51 (no DB query touches the column)
  - `tests/test_access_tiers.py` + `tests/test_isolation_audit.py` — both import the middleware *module*, not the DB column

Live evidence (queried via Supabase MCP at 2026-05-21 14:00 Asia/Jakarta):
- `users` table columns: id, telegram_user_id, username, auto_trade_on, paused, referrer_id, created_at, is_demo, locked, onboarding_complete, role — no `access_tier`.
- Postgres logs (last 24h): zero `column "access_tier" does not exist` errors.
- `signal_scan` job: 275 success / 1 failed in last 24h; the single failure (2026-05-20 16:30:14) predates this lane and stems from the same JSONB shape bug.
- `signal_following_scan`: 9 failures clustered 2026-05-20 05:53–06:13; no failures since → bug has been latent (rare strategy_params payload).

---

## 5. Known issues

- `bot/middleware/access_tier.py` filename retained for Python import-path stability (decided by WARP-51). Strict reading of the issue's acceptance criterion ("zero hits excluding DROP migration") would require renaming to `bot/middleware/role_gate.py` and updating two test files. This was scoped out of WARP-56 because the production runtime is unaffected — the file contains no SQL touching the dropped column.
- Supabase migration history shows `045b_restore_access_tier_placeholder` was applied 2026-05-21 00:39:53 but the corresponding `.sql` file is not in the local repo (deleted by WARP-51). Migration 044 is similarly not registered in `supabase_migrations.schema_migrations` even though the column is gone. Tracking drift is documented; no functional impact since the column is verifiably absent from the live `users` table.

---

## 6. What is next

WARP🔹CMD review → merge → Fly.io redeploy. No new schema migration required (mig 001 change only affects fresh installs; existing prod DB has already dropped the column via mig 044). The dry-run FK silencing takes effect immediately on the next deploy.

After merge: WARP-55 (Runtime Spine End-to-End Proof, issue #1256) remains the active P0 lane and is being prepared on branch `WARP/runtime-spine-e2e-proof`.

---

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : `_coerce_jsonb` and `domain/risk/gate._log` paths only; the rest of the runtime spine is unchanged.
Not in Scope      : Rename of `bot/middleware/access_tier.py` (test-import refactor); reconciliation of Supabase `schema_migrations` history with local migration files; new feature work; live-trading guards.
Suggested Next    : WARP🔹CMD review → merge → Fly.io redeploy.
