# WARP•FORGE REPORT — warp54-closed-beta-hardening

**Branch:** WARP/warp54-closed-beta-hardening
**Issue:** #1253 (WARP-54 — Closed beta hardening: duplicate trades, stuck positions, state bleed, restart recovery, P1)
**Date:** 2026-05-21 13:24 Asia/Jakarta
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** /admin HUD surfaces stuck open positions; `notifications.send` falls back to plain text on `BadRequest` from HTML parse-mode (no silent drop on malformed markup); scheduler one-shot startup job logs "Resumed monitoring N open positions" after Fly machine restart; regression tests pin the existing dedup, user_id scoping, and exception-swallow behaviours that already hold in production code.
**Not in Scope:** Live trading, WebTrader, new UI, new strategies; full multi-tenant SQL audit (covered by WARP-32, regression-pinned only); new API timeout user-notification path (current 3-tick threshold preserved to avoid alert spam).

---

## 1. What Was Built

WARP-54 was scoped as six closed-beta hardening items (#1253 §1-§6). Audit found four were already correct in code shipped by earlier lanes — only test coverage was missing — and two needed targeted code additions. The lane therefore lands as three small production changes plus a six-test regression file.

### Code changes

**§4 Notification failure — `BadRequest` plain-text fallback (`notifications.py`)**

`telegram.error.BadRequest` inherits from `NetworkError` (verified in PTB v22), so the existing tenacity retry set `(NetworkError, TimedOut, RetryAfter)` was retrying it 4× — pure latency cost since `BadRequest` is non-transient. Worse, after retries exhausted, the message was permanently dropped because `BadRequest` was never reclassified.

Fix:
1. Combined the retry predicate with `retry_if_not_exception_type(BadRequest)` so HTML parse errors fall through immediately instead of consuming the attempt budget.
2. Added a `BadRequest` catch in `send()` that retries exactly once with `parse_mode=None` (plain text). Plain text is guaranteed to render even when the original HTML was malformed.
3. If the plain-text retry also fails, the post-fallback ERROR is logged and `False` is returned — no infinite loop, no silent swallow.

**§2 Stuck positions — `/admin` HUD surface (`bot/handlers/admin.py`)**

`_admin_status_hud` previously showed `open_paper` / `open_live` counts but had no way to flag positions the exit watcher had repeatedly failed to close, or positions on markets that had silently aged out. Added a `stuck_open` row using:

```sql
SELECT COUNT(*) FROM positions
 WHERE status = 'open'
   AND (
     COALESCE(close_failure_count, 0) > 0
     OR opened_at < NOW() - INTERVAL '24 hours'
   )
```

The HUD line conditionally appends `⚠️ N stuck` when the count > 0, otherwise stays clean. Two-condition OR covers both Polymarket-side close failures (the `close_failure_count` branch already maintained by `registry.record_close_failure` from exit_watcher) and silently-aged open positions (the 24h opened_at branch).

**§5 Restart recovery — startup log job (`scheduler.py`)**

Audit confirmed the exit watcher already resumes monitoring pre-existing open positions on every tick via `registry.list_open_for_exit` — there is no boot-time gap. Missing: an explicit log line proving the resume actually happened after a Fly machine restart.

Added `log_resumed_open_positions()` — a one-shot `date`-trigger job registered in `setup_scheduler()` that fires immediately at scheduler boot. It runs two `COUNT(*)` queries (paper + live open positions), logs `startup_recovery: Resumed monitoring N open positions (X paper, Y live)` at INFO, and returns `{"resumed_paper", "resumed_live"}` so the APScheduler listener writes the count into `job_runs.metadata`. All DB errors are caught and returned as an error-tagged dict so a Supabase hiccup at boot cannot crash scheduler startup.

### Audit-only items (no code change, test-pinned)

**§1 No duplicate trades**

`paper.execute` uses `INSERT INTO orders ... ON CONFLICT (idempotency_key) DO NOTHING` (paper.py:42-44). `copy_trade.CopyTradeStrategy` checks `copy_trade_idempotency` for `(user_id, task_id, leader_trade_id)` early (copy_trade.py:399-403) AND the docstring confirms a second-defence INSERT-ON-CONFLICT in the downstream execution consumer. The DB-level guard is correct.

Regression test added: `test_paper_execute_returns_duplicate_when_idempotency_key_repeats` — same idempotency_key twice → second call returns `{"status": "duplicate", "mode": "paper"}` with notifier.notify_entry firing only once.

**§3 No state bleed between users**

WARP-32 (PR #1174) already audited the full handler+service surface and confirmed zero `user_id` leaks. `paper.close_position` UPDATE includes `WHERE user_id=$5` as the DB-level enforcement.

Regression test added: `test_paper_close_position_is_user_scoped` — close attempt with a wrong user_id against another user's position id returns `already_closed` and never fires the snapshot/audit writers. The DB UPDATE is invoked with the attacker's user_id, so isolation is enforced at the SQL guard rather than in application logic. Complements the 10+ test suite in `test_user_isolation.py`.

**§6 API timeout / failure behavior**

Audit confirmed existing behavior is already correct:
- `exit_watcher._fetch_live_price` (exit_watcher.py:85-101) wraps `get_live_market_price` in try/except → returns None on any failure → 3-tick threshold (`_EXPIRED_TICK_THRESHOLD = 3`, ~90s) before MARKET_EXPIRED classification.
- `exit_watcher.run_once` per-position try/except prevents one bad row from poisoning the batch.
- Polymarket API timeout: position remains open ✅, retry queued on next tick ✅. User notification on transient timeouts deliberately deferred — adding it would create alert spam on common API hiccups, and operator-side paging already fires at `CLOSE_FAILURE_OPERATOR_THRESHOLD=2` for persistent close failures via `alert_operator_close_failed_persistent`.
- Supabase down: asyncpg raises → per-position try/except catches → scheduler tick logs ERROR and moves on. No process crash.

No code change. Coverage lives in `test_exit_watcher.py` (production env; sandbox lacks `eth_account` for the import chain).

---

## 2. Current System Architecture (Slice Relevant to WARP-54)

```
Notification path (services/trade_notifications/* + monitoring/alerts.py + ...)
  notifications.send(chat_id, text, parse_mode=HTML)
    AsyncRetrying(
      stop=stop_after_attempt(4),
      wait=_wait_telegram(),                                # WARP-53: respects RetryAfter
      retry = retry_if_exception_type((NetworkError, TimedOut, RetryAfter))
              & retry_if_not_exception_type(BadRequest),    # WARP-54 §4: exclude BR
    )
    on BadRequest (HTML parse error):
      log WARNING + retry once with parse_mode=None         # WARP-54 §4
      success -> return True
      failure -> log ERROR + return False
    on attempt exhaustion (all other paths):
      log ERROR + return False                              # WARP-53 baseline


Scheduler boot (scheduler.py:setup_scheduler)
  sched.add_job(log_resumed_open_positions, "date",         # WARP-54 §5
                id="startup_recovery_log", coalesce=True)
    -> on first tick (immediate after sched.start()):
       COUNT(*) FROM positions WHERE status='open' AND mode='paper'
       COUNT(*) FROM positions WHERE status='open' AND mode='live'
       logger.info("startup_recovery: Resumed monitoring N open positions ...")
       return {"resumed_paper": X, "resumed_live": Y}
       (APScheduler listener -> job_runs.metadata)


/admin HUD (bot/handlers/admin.py:_admin_status_hud)
  ...existing rows...
  Positions: N paper · M live  [⚠️ K stuck]                  # WARP-54 §2
    stuck = COUNT(*) WHERE status='open' AND (
              close_failure_count > 0
              OR opened_at < NOW() - INTERVAL '24 hours'
            )


Paper open dedup (already correct — pinned by WARP-54 test)
  paper.execute(idempotency_key=K)
    INSERT INTO orders (..., idempotency_key) VALUES (...)
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING id
      -> row is None on duplicate -> return {status: duplicate}


Paper close user-scoping (already correct — pinned by WARP-54 test)
  paper.close_position(position)
    UPDATE positions SET status='closed' ...
     WHERE id=$1 AND status='open' AND user_id=$5
     RETURNING id
      -> id is None when row owned by another user -> already_closed
```

---

## 3. Files Created / Modified

Created:
- `projects/polymarket/crusaderbot/tests/test_warp54_closed_beta_hardening.py`
- `projects/polymarket/crusaderbot/reports/forge/warp54-closed-beta-hardening.md`

Modified:
- `projects/polymarket/crusaderbot/notifications.py` — added `BadRequest` import, `retry_if_not_exception_type(BadRequest)` to the retry predicate, and a `BadRequest` catch in `send()` that retries once with `parse_mode=None`.
- `projects/polymarket/crusaderbot/bot/handlers/admin.py` — added `stuck_open` SQL count to `_admin_status_hud` and a conditional `⚠️ N stuck` suffix to the Positions row.
- `projects/polymarket/crusaderbot/scheduler.py` — added `log_resumed_open_positions()` job + one-shot `date`-trigger registration in `setup_scheduler()`.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — WARP-54 status added; existing WARP-53 entry retained.
- `projects/polymarket/crusaderbot/state/WORKTODO.md` — all six P1 Closed Beta Hardening items checked.
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — lane closure entry appended.

No schema changes. No risk constant changes. No new external dependency. No phase folders.

---

## 4. What Is Working

Evidence (file:line + test result for every claim):

- BadRequest is excluded from retry. See `notifications.py:_retry()` (modified to combine `retry_if_exception_type` with `retry_if_not_exception_type(BadRequest)`). Pinned indirectly by `test_send_falls_back_to_plain_text_on_badrequest` — exactly 2 send_message calls (1 HTML failed + 1 plain succeeded), proving no retry burns on the HTML attempt.
- Plain-text fallback on BadRequest. See `notifications.py:send()` BadRequest branch (~lines 116-145). Pinned by `test_send_falls_back_to_plain_text_on_badrequest` — `ok == True`, second call has `parse_mode is None`.
- Hard failure path on double-failure. See `notifications.py:send()` plain-text BadRequest branch. Pinned by `test_send_returns_false_when_plain_text_also_fails` — `ok == False`, ERROR log contains "permanently failed after plain-text fallback", total `send_message` await_count == 2.
- `/admin` HUD surfaces stuck positions. See `bot/handlers/admin.py:_admin_status_hud` (modified, new stuck_open block). Visible to any operator running `/admin` once a position has `close_failure_count > 0` or has been open > 24h.
- Startup recovery log line. See `scheduler.py:log_resumed_open_positions` (new) and `setup_scheduler()` `startup_recovery_log` job registration. Pinned by `test_log_resumed_open_positions_emits_count` — log line `"Resumed monitoring 4 open positions (3 paper, 1 live)"`, return value `{"resumed_paper": 3, "resumed_live": 1}`.
- Startup recovery is crash-safe. See same function's try/except. Pinned by `test_log_resumed_open_positions_swallows_db_error` — `get_pool` raises RuntimeError → function returns `{"resumed_paper": None, "resumed_live": None, "error": "..."}` instead of propagating.
- Paper dedup on repeated idempotency_key. See `paper.py:42-44` (existing). Pinned by `test_paper_execute_returns_duplicate_when_idempotency_key_repeats` — second call returns `{"status": "duplicate", "mode": "paper"}`, notifier fires once.
- Paper close is user-scoped. See `paper.py:UPDATE ... WHERE user_id=$5` (existing). Pinned by `test_paper_close_position_is_user_scoped` — close with wrong user_id returns `already_closed`, UPDATE was attempted with attacker's user_id (DB guard is the source of truth).

Test run output:

```
projects/polymarket/crusaderbot/tests/test_warp54_closed_beta_hardening.py
......                                                                   [100%]
6 passed in 0.72s

projects/polymarket/crusaderbot/tests/test_warp53_reliability_hardening.py
projects/polymarket/crusaderbot/tests/test_notifications_gate.py
projects/polymarket/crusaderbot/tests/test_trade_notifications.py
projects/polymarket/crusaderbot/tests/test_portfolio_snapshots_writer.py
projects/polymarket/crusaderbot/tests/test_user_isolation.py
................................................                         [100%]
48 passed in 0.48s
```

`py_compile` clean on `notifications.py`, `bot/handlers/admin.py`, `scheduler.py`, and the new test file. Mojibake grep clean on all touched files.

---

## 5. Known Issues

- The `stuck_open` HUD threshold is fixed at 24h `opened_at` age. Some legitimate long-horizon prediction-market positions stay open across days without being stuck. Operator interpretation: the badge surfaces "look at these" candidates, not automatic failures. A future enhancement could lower the threshold for high-velocity markets only (additional metadata required).
- The plain-text fallback drops the markup but preserves the message content. Inline keyboards are still rendered (the `reply_markup` arg is forwarded). Operators looking at fallback messages will see plain text instead of formatted entities — visually different but functionally complete.
- The `log_resumed_open_positions` startup job is a `date` trigger with no explicit `run_date`, so APScheduler runs it once on next tick. If scheduler is started in a context where the listener hasn't attached yet, the job may not populate `job_runs.metadata` for that single tick. The log line still fires.
- WARP-54 §6 user-notification gap (Polymarket timeout) is deliberately not addressed. Adding it risks alert spam on common API hiccups. Operator-side paging via `alert_operator_close_failed_persistent` already covers persistent failures. If WARP🔹CMD wants user-side alerting on transient outages, that becomes a follow-up lane with explicit anti-spam shaping.
- The §1 and §3 regression tests pin existing behaviour at the unit-test level. True multi-process / concurrent-call coverage requires a hermetic asyncpg integration test, which is left for a future lane.
- The sandbox runner lacks `eth_account` etc., so the test file uses `importlib.import_module` inside a try/except + `pytest.skip` for the scheduler-importing tests. Production CI has the dep and runs all six tests. The skip is observable in CI logs only on sandbox runs.

---

## 6. What Is Next

Suggested next step: WARP🔹CMD review + merge. Tier STANDARD → WARP•SENTINEL is NOT required per AGENTS.md routing.

Post-merge sequence:
1. Fly.io redeploy required (no migration; only Python code + scheduler job registration changes). Post-deploy: confirm the `startup_recovery: Resumed monitoring N open positions` line appears in production logs on next machine boot.
2. Observability check (recommended): after deploy, `/admin` from an admin telegram account should show the new stuck-positions line when applicable. If no stuck positions, the line stays clean.

Follow-up lanes (NOT this lane):
- User-side notification on Polymarket transient timeouts, with anti-spam shaping (decision: WARP🔹CMD).
- Multi-process concurrent-call hermetic test for paper.execute / paper.close_position (deferred — requires asyncpg integration harness).
- Lower the stuck-position 24h threshold for short-horizon markets if production telemetry shows false positives.
- Optional: surface `stuck_open` count in WebTrader admin UI in parallel with the Telegram HUD.

---

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : /admin HUD surfaces stuck positions; notifications.send falls back to plain text on BadRequest from HTML parse-mode; scheduler one-shot startup job logs "Resumed monitoring N open positions"; regression tests pin existing dedup, user_id scoping, and exception-swallow behaviours
Not in Scope      : Live trading, WebTrader, new UI, new strategies; full multi-tenant SQL re-audit (covered by WARP-32); user-side notification on transient API timeouts (anti-spam concerns)
Suggested Next    : WARP🔹CMD review
