# WARP•SENTINEL Report — P3d Signal Scan + Execution Queue

Branch: WARP/CRUSADERBOT-P3D-SIGNAL-SCAN-EXECUTION-QUEUE
PR: #897
Head SHA: 0e99bb413598b1614979b6b06f3063624755ea2f
Date: 2026-05-07 23:45 Asia/Jakarta
Tier: MAJOR
Claim Level: FULL RUNTIME INTEGRATION (scoped P3d path — signal_following scan loop, execution queue, risk gate wiring)

---

## TEST PLAN

Environment: dev (no live capital, activation guards NOT SET)
Pipeline stages validated: Enrolled-user load → strategy.scan → risk gate → execution_queue insert → router_execute → queue status update
Validation target:
- STRATEGY_AVAILABILITY["signal_following"] key matches strategy name + risk_profile_compatibility
- Risk gate is mandatory before every queue insert or router_execute call
- execution_queue UNIQUE partial index prevents re-execution across scan ticks
- subscribe/unsubscribe enrollment wired through user_strategies
- Activation guards NOT SET and NOT mutated in new code
- Kelly fraction unchanged at 0.25
- CI green

Phases executed: 0 (Pre-Test), 1 (Functional), 2 (Pipeline E2E), 3 (Failure Modes),
4 (Async Safety), 5 (Risk Rules), 6 (Latency), 7 (Infra), 8 (Telegram)

---

## FINDINGS

### Phase 0 — Pre-Test

- PASS: Forge report at correct path with all 6 mandatory sections
  `projects/polymarket/crusaderbot/reports/forge/p3d-signal-scan-execution-queue.md`
- PASS: PROJECT_STATE.md updated (Last Updated: 2026-05-07 22:30 Asia/Jakarta)
- PASS: No phase*/ folders or legacy paths detected
- PASS: Hard-delete policy followed — no migrated files at original path
- PASS: Implementation evidence present for all critical layers
- NOTE: PROJECT_STATE.md on PR HEAD was pre-populated with a sentinel verdict (96/100)
  before this validation run. Scored independently. Final score: 94/100.

### Phase 1 — Functional Testing

- PASS: 24 hermetic tests in `tests/test_signal_scan_job.py`
  All required paths covered: happy path, dedup (pre-check + concurrent), rejection,
  router failure, market not synced, gate context build error, scan isolation per user.
- PASS: 3 additional tests verify STRATEGY_AVAILABILITY match:
  `test_signal_following_matches_strategy_name` (file:line 149)
  asserts `strategy.name == "signal_following"`,
  `strategy.name in K.STRATEGY_AVAILABILITY`, and
  `set(strategy.risk_profile_compatibility) == set(K.STRATEGY_AVAILABILITY["signal_following"])`
- PASS: 4 tests in `tests/test_signal_following.py` cover subscribe/unsubscribe enrollment
- PASS: CI Lint + Test → success (both runs, completed 2026-05-07T17:45:07Z)
- MINOR-01: Forge report states "459/459 tests green"; PR body states "463/463".
  Delta = 4 (test_signal_following.py tests added after forge report written).
  CI confirms actual passing count. Not a blocker.

### Phase 2 — Pipeline End-to-End

- PASS: `signal_scan_job.py` — full path verified:
  `_load_enrolled_users` → `strategy.scan` → `_publication_already_queued` →
  `_load_market` → `_build_gate_context` → `risk_evaluate` → `_insert_execution_queue`
  → `router_execute` → `_mark_executed` / `_mark_failed`
- PASS: No bypass path exists — `router_execute` is inside the
  `if not result.approved: return` guard (signal_scan_job.py:258)
- PASS: `_insert_execution_queue` only reached after `result.approved = True`
- PASS: scheduler.py: `signal_following_scan` job wired at
  `sf_scan_job.run_once, SIGNAL_SCAN_INTERVAL, max_instances=1, coalesce=True` (scheduler.py:258)
- PASS: Old `run_signal_scan` (copy_trade) runs in parallel — no interference;
  each job has its own `max_instances=1` guard

### Phase 3 — Failure Modes

- PASS: `_load_enrolled_users` failure → log + early return; tick does not crash
  (signal_scan_job.py:303)
- PASS: Strategy not registered → log + early return (signal_scan_job.py:313)
- PASS: Per-user scan failure isolated; other users in tick unaffected
  (signal_scan_job.py:329 — outer try/except per user loop)
- PASS: Market not synced → `"skipped_market_not_synced"` log, return
  (signal_scan_job.py:221)
- PASS: Risk rejection → `"rejected"` log with reason + failed_step, return
  (signal_scan_job.py:247)
- PASS: Router raises → `_mark_failed` + `"failed"` log; scan continues
  (signal_scan_job.py:281)
- PASS: Concurrent tick race → `ON CONFLICT DO NOTHING` returns False →
  `"skipped_concurrent_dedup"` log, return (signal_scan_job.py:261)
- PASS: Dedup pre-check failure (DB error) → log warning + assumes not-queued
  (signal_scan_job.py:215) — safe fallback; gate idempotency_keys catches the dup
- MINOR-04: When `pub_uuid is None`, the pre-check dedup (execution_queue UNIQUE
  partial index) does not apply — the index is `WHERE publication_id IS NOT NULL`.
  Multiple NULL-pub rows can accumulate; inner idempotency_keys (30 min) mitigates
  but does not permanently prevent re-runs. For signal_following, candidates carry
  a publication_id from signal_publications; this is a theoretical edge case only.

### Phase 4 — Async Safety

- PASS: No `import threading` anywhere in new files
- PASS: All DB calls use `async with pool.acquire()` — no sync DB calls
- PASS: `subscribe()` uses `pg_advisory_xact_lock(hashtext($1))` to serialise
  concurrent cap checks — no race condition possible (signal_feed_service.py:193)
- PASS: `_insert_execution_queue` uses `ON CONFLICT DO NOTHING RETURNING id`
  — concurrent tick safety at the DB boundary (signal_scan_job.py:103)
- PASS: `_mark_executed` and `_mark_failed` are idempotent; double-call is a no-op
- PASS: Exception isolation per candidate: outer `try/except` in candidate loop
  (signal_scan_job.py:329) — no state corruption across users

### Phase 5 — Risk Rules

- PASS: `KELLY_FRACTION = 0.25` (constants.py:8)
- PASS: Gate step 13 asserts: `assert 0 < K.KELLY_FRACTION <= 0.5` (gate.py:171)
  Full Kelly (a=1.0) structurally impossible
- PASS: `MAX_POSITION_PCT = 0.10` (constants.py:9)
- PASS: `DAILY_LOSS_HARD_STOP = -2_000.0` (constants.py:12)
- PASS: `MAX_DRAWDOWN_HALT = 0.08` (constants.py:13)
- PASS: `MIN_LIQUIDITY = 10_000.0` (constants.py:14)
- PASS: `STRATEGY_AVAILABILITY["signal_following"] = ["conservative","balanced","aggressive"]`
  (constants.py:38)
- PASS: Kill switch checked at gate step 1 — live_fallback triggered on live user
  (gate.py:68)
- PASS: Activation guards verified in `_passes_live_guards`:
  `ENABLE_LIVE_TRADING AND EXECUTION_PATH_VALIDATED AND CAPITAL_MODE_CONFIRMED AND access_tier>=4`
  (gate.py:130) — none set, all new code defaults to paper mode
- PASS: `trading_mode` sourced from `user_settings.trading_mode` (default 'paper');
  no new code sets or mutates any activation flag
- PASS: Signal dedup: idempotency_keys 30-min window (gate step 10) +
  execution_queue UNIQUE partial index (outer permanent dedup)

### Phase 6 — Latency

- PASS: No HTTP calls in scan path — market data from synced `markets` table
- PASS: `strategy.scan()` is pure DB reads (signal_publications, user_signal_subscriptions)
- PASS: Risk gate DB calls use connection pool — no connection setup overhead per call
- MINOR-05: No explicit per-tick latency instrumentation (ingest / signal / exec timing)
  in signal_scan_job.py. APScheduler `max_instances=1` prevents overlapping ticks
  but does not bound or record actual tick duration. Low priority — covered by
  job_tracker (scheduler.py:285) which records job-level duration.

### Phase 7 — Infra

- PASS: `migrations/011_execution_queue.sql` — idempotent (`IF NOT EXISTS` on all DDL)
  Table, UNIQUE partial index, and support indexes all safe to re-run
- PASS: `migrations/012_backfill_signal_following_strategy.sql` — idempotent
  (`INSERT ... ON CONFLICT (user_id, strategy_name) DO UPDATE SET enabled = TRUE`)
- PASS: PostgreSQL FK: `execution_queue.user_id REFERENCES users(id) ON DELETE CASCADE`
- PASS: Subscribe path writes `user_strategies` enrollment atomically within same
  transaction as subscription insert (signal_feed_service.py:225)
- PASS: Unsubscribe path disables `user_strategies.enabled` when no active
  subscriptions remain (signal_feed_service.py:271)
- NOTE: Redis not used directly in scan path — idempotency_keys table (PostgreSQL)
  used for 30-min dedup window. Consistent with prior approved system design.

### Phase 8 — Telegram

- PASS: Kill switch accessible via existing Telegram commands (prior PR, unchanged)
- PASS: `router_execute` (paper path) triggers existing trade notifications from
  prior PRs when a candidate is accepted and executed
- MINOR-06: Scan-level outcomes (accepted / rejected / skipped_dedup / failed) are
  emitted via structlog only — no Telegram alert to the user. A user subscribed to
  a feed cannot observe why their signal_following did not execute on a given tick.
  By design for a background job (no per-tick spam); operator observability via
  structured logs. No Telegram commands added in P3d scope.
- PASS: No new bot commands in P3d scope — Telegram surface unchanged

---

## CRITICAL ISSUES

None found.

---

## STABILITY SCORE

| Category | Weight | Score | Notes |
|---|---|---|---|
| Architecture | 20% | 19/20 | Dual-layer dedup, mandatory gate, user isolation. -1 MarketFilters hardcoded |
| Functional | 20% | 19/20 | 24+4 tests, all paths covered, CI green. -1 forge/PR count discrepancy |
| Failure Modes | 20% | 19/20 | All modes handled. -1 NULL pub_uuid permanent dedup gap |
| Risk Rules | 20% | 20/20 | Kelly 0.25 asserted, all guards verified, STRATEGY_AVAILABILITY correct |
| Infra + Telegram | 10% | 8/10 | Migrations idempotent, DB correct. -1 no scan-level TG alerts, -1 no explicit Redis usage |
| Latency | 10% | 9/10 | No HTTP in scan path. -1 no per-tick latency instrumentation |
| **Total** | **100%** | **94/100** | |

---

## GO-LIVE STATUS

**VERDICT: APPROVED**

Score: 94/100. Zero critical issues. All mandatory risk rules verified in code.
Risk gate is structurally mandatory — no path to execution without approval.
Activation guards are NOT SET and NOT mutated. System defaults to paper mode
for all signal_following candidates under current configuration.
Dual-layer deduplication prevents re-execution across scan ticks.
Asyncio-only, per-user scan isolation, idempotent migrations.

P3d is safe to merge. Final deployment decision rests with WARP🔹CMD.

---

## FIX RECOMMENDATIONS

No critical fixes required. Minor items for future lanes:

- MINOR-01 (LOW): Update forge report test count from 459 to 463. Cosmetic.
- MINOR-04 (LOW): Add execution_queue dedup path for NULL publication_id candidates
  (non-blocking — signal_following always provides pub_id; only affects future
  strategies that omit publication_id).
- MINOR-05 (LOW): Add per-tick duration logging in `run_once()` to surface
  ingest / scan / exec latency in structured logs.
- MINOR-06 (LOW): Consider a daily digest Telegram alert summarising signal_following
  scan activity (accepted / rejected counts) for subscribed users. Avoids per-tick
  spam while giving users observability.
- Unused `struct` import in `signal_scan_job.py:10` — part of pre-existing F401
  cleanup backlog (KNOWN ISSUES). Remove in ruff cleanup lane.

---

## TELEGRAM PREVIEW

No new Telegram commands or alert types introduced in P3d.

Existing flow when a candidate is accepted:
```
[router_execute (paper)] → existing position-open notification
✅ Trade executed: signal_following
Market: [question]
Side: YES | Size: $X.XX USDC | Mode: paper
```

Kill switch (unchanged, accessible to operator):
```
/killswitch on   → halts all scan ticks at gate step 1
/killswitch off  → resumes scan
```

Scan-level rejection/dedup outcomes: structlog only (no user Telegram alert).
Daily P&L summary (existing, unchanged) provides net position visibility.
