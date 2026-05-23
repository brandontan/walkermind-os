# WARP•FORGE Report — Runtime Bugfix

- Branch: `WARP/CRUSADERBOT-RUNTIME-BUGFIX`
- Linear: WARP-40 (Lane 2 — Runtime Bugfix), depends on WARP-39 (merged)
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target: exit_watch → job_runs type safety (DAWN-5); zero `access_tier` column references (DAWN-1K); `signal_scan_job.run_once` survives unexpected `strategy_params` types (DAWN-1Q).
- Not in Scope: re-adding the `access_tier` column (deliberately dropped, mig 044); WARP-39 infra items; Fly redeploy; marking Sentry issues resolved.
- Suggested Next Step: WARP🔹CMD review + merge, then Fly.io redeploy so the running pod picks up the guard; resolve the three Sentry issues once redeploy confirms no new events.

---

## 1. What was built

WARP-40 targets three Sentry runtime errors. On inspection, FIX 1 and FIX 2 were already fully resolved by prior merged PRs, and FIX 3's primary path (top-level `strategy_params`) was already guarded. This lane closes the one genuine remaining sub-gap in FIX 3 and verifies the rest against code (file:line evidence below).

Change made (1 file):

- FIX 3 — `services/signal_scan/signal_scan_job.py` `run_once()`: the per-strategy params sub-value `strategy_params.get(lib_name, {})` was passed to the lib strategy without a type check. `_coerce_jsonb` guarantees the top-level value is a dict, but a malformed user row (e.g. `{"momentum_reversal": "balanced"}`) can still hold a non-dict sub-value, which would raise `ValueError: dictionary update sequence element #0 has length 1; 2 is required` when the strategy consumes it. Added an `isinstance(..., dict)` guard that drops the bad value to `{}` and logs `signal_scan_strategy_params_not_dict` with the offending type name.

Verified already-resolved (no change, evidence):

- FIX 1 (DAWN-5, exit_watch dict→str): the sole `job_runs` writer is `domain/ops/job_tracker.py:record_job_event`. It already serializes the metadata dict — `json.dumps(metadata) if metadata is not None else None` (`job_tracker.py:89`) — bound to `$6::jsonb` (`job_tracker.py:87`). The scheduler listener only ever forwards a dict-or-None (`scheduler.py:564`, `metadata = retval if isinstance(retval, dict) else None`). No raw dict reaches a str-typed column on any path.
- FIX 2 (DAWN-1K, `access_tier` UndefinedColumnError): no query, model, or migration references the `access_tier` column. Repo-wide grep shows the only surviving mentions are the renamed middleware file's docstring (`bot/middleware/access_tier.py`, kept for import-path stability) and migration `044_drop_access_tier.sql` (the `DROP COLUMN IF EXISTS`). Access gating runs entirely on `users.role` (mig 045) — `_load_enrolled_users` selects `u.role` (`signal_scan_job.py:162`). WARP-51 swept all Python writers/readers; the 110 events are historical (pre-merge).
- FIX 3 primary path: `_coerce_jsonb` (`signal_scan_job.py:120-142`) already coerces the top-level `strategy_params` JSONB to a dict and falls back to `{}` for scalars/malformed JSON — its docstring cites the exact DAWN-1Q ValueError. `run_once` itself contains no direct `dict()`/`.update()` on DB values.

## 2. Current system architecture

- Scan loop: `signal_scan_job.run_once()` loads enrolled users (`role`-based, no `access_tier`), coerces user JSONB via `_coerce_jsonb`, and now type-guards each per-strategy params sub-value before constructing `config` for the lib strategy. Lib-strategy execution remains wrapped in try/except (`lib_strategy_run_failed`), so a single bad strategy never aborts the tick.
- Job observability: every scheduler job execution writes one `job_runs` row via `job_tracker.record_job_event`, with the metadata dict JSON-serialized into the `metadata::jsonb` column. Write failures are swallowed + logged so observability never breaks the trading loop.
- Access control: two-role RBAC on `users.role` (`admin`/`user`); the integer `access_tier` column was dropped in migration 044.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` (modified — per-strategy params dict guard in `run_once`)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` (state sync)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` (lane entry)
- `projects/polymarket/crusaderbot/reports/forge/runtime-bugfix.md` (this report)

## 4. What is working

- `run_once` now logs and skips a non-dict per-strategy params value instead of forwarding it into a strategy that would crash on `dict()`/`.update()`.
- `py_compile` clean on the modified module.
- FIX 1 and FIX 2 confirmed resolved in code with file:line evidence; no regression introduced.

## 5. Known issues

- The 3 Sentry issues (DAWN-5, DAWN-1K, DAWN-1Q) accumulated events before the prior fixes shipped. They will only stop after a Fly.io redeploy of current main + this branch; resolve them in Sentry once redeploy confirms zero new events.
- Full pytest not exercised in this remote container (asyncpg/telegram/cryptography binding chain unavailable — same posture as recent lanes). The change is a single mechanical type guard; WARP🔹CMD or CI should run `pytest projects/polymarket/crusaderbot/tests/` (notably any `test_warp56_sentry_fix` / signal_scan tests) before merge.

## 6. What is next

- WARP🔹CMD review + merge (STANDARD — no SENTINEL).
- Fly.io redeploy so the running pod imports the guarded scanner.
- After redeploy stabilizes, mark DAWN-5 / DAWN-1K / DAWN-1Q resolved in Sentry.
