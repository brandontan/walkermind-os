# WARP•FORGE REPORT — warp53-reliability-hardening

**Branch:** WARP/warp53-reliability-hardening
**Issue:** #1252 (WARP-53 — Telegram notification reliability + paper trading consistency, P0)
**Date:** 2026-05-21 12:57 Asia/Jakarta
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Telegram delivery path honours Telegram's mandated 429 RetryAfter wait instead of fixed exponential backoff; every per-event notification call site logs a WARNING when delivery is dropped (no silent swallow); paper.close_position double-close idempotency is pinned by an explicit regression test.
**Not in Scope:** Live trading paths, WebTrader, UI changes, new features, ledger schema changes, manual close UX, restart recovery (WARP-54), user_id isolation audit (WARP-54), parse_mode=HTML fallback (WARP-54).

---

## 1. What Was Built

Two reliability gates landed on top of the existing notification + paper-close primitives — no new behaviour, no widened surface. Each gate closes one of the two WARP-53 scope items.

### Gate 1 — Telegram delivery honours 429 RetryAfter

Audit found `notifications.py:38-44` used `wait_exponential(multiplier=1, min=1, max=8)`, which IGNORED the `RetryAfter.retry_after` value Telegram returns on rate-limit. A typical 429 with `retry_after=30` would burn the entire 3-attempt budget in `~1+2+4=7s` and return a permanent failure — the user-side trade receipt would be permanently dropped on every rate-limit episode.

Fix: a custom `_wait_telegram(wait_base)` strategy that returns `min(retry_after, 30s)` when the raised exception is `RetryAfter`, falling back to the exponential schedule for `NetworkError` / `TimedOut`. Max attempts bumped from 3 → 4 so a single capped-30s wait does not exhaust the budget before a healthy attempt gets through. Worst-case wall: one 30s capped wait + three sub-10s exponential waits.

### Gate 2 — Per-event "no silent swallow" WARNING

Audit found seven send call sites that discarded the `bool` return of `notifications.send`. `notifications.send` itself logs the permanent failure at ERROR, but the log line has no event context — a dropped TP receipt looks identical in logs to a dropped onboarding nudge. WARP-53's "no silent swallow" gate requires per-event surface area so operators can tell which trade-lifecycle event was lost.

Fix: each call site now branches on the return value and emits a WARNING tagged with its event identity:
- `services/trade_notifications/notifier.py:_send` — tag = `notification_event` (entry / tp_hit / sl_hit / manual / emergency / copy_trade)
- `services/trade_notifications/notifier.py:_edit_or_resend` — tag = `chat`, `message_id` for animated-entry fallback drop
- `services/notification_service.py:_send_safe` — tag = `event_name` (position.opened / position.closed / copy_trade.executed / trade.blocked)
- `monitoring/alerts.py:_send_user_exit_alert` (new helper) — tag = `alert_kind` (tp_hit / sl_hit / force_close / strategy_exit / manual_close / market_expired / close_failed) — replaces 7 raw `await notifications.send(...)` calls

### Paper trading consistency

Audit confirmed the WARP-53 §2 requirements are ALREADY satisfied by code shipped in WARP-52 + WARP-25b:
- `paper.close_position` runs UPDATE positions + ledger.credit_in_conn under a single `conn.transaction()` — atomicity is real.
- The UPDATE has `WHERE id=$1 AND status='open' AND user_id=$5` so a second close is a no-op at the DB level (returns `exit_reason='already_closed'`).
- `portfolio_snapshots.write_snapshot` is fired AFTER txn commit and ONLY on the happy-close branch — never on the no-op re-close.

Missing: a Python-side regression test pinning the double-close behaviour. The WARP-52 test suite proves "no snapshot when already closed" but not "second call returns already_closed AND fires no ledger writes AND fires no audit". Test added (`test_paper_close_position_idempotent_under_double_close`).

No paper-engine code change — the existing guards are correct; only the test surface needed strengthening.

---

## 2. Current System Architecture (Slice Relevant to WARP-53)

```
Telegram send (single source: projects/polymarket/crusaderbot/notifications.py)

  notifications.send(chat_id, text, ...)
    AsyncRetrying(
      stop_after_attempt(4),                          # bumped from 3
      wait=_wait_telegram(),                          # NEW: respects RetryAfter
      retry on (NetworkError | TimedOut | RetryAfter)
    )
    -> attempt: bot.send_message(...)
       on RetryAfter(retry_after=N):
         next wait = min(N, 30s)                      # was: exp backoff (1-8s)
       on NetworkError / TimedOut:
         next wait = exp(min=1, max=8)
       budget exhausted -> log ERROR + return False   # unchanged, never raises

Per-event call sites (all now branch on bool return):

  domain/execution/exit_watcher.py
    -> monitoring/alerts.alert_user_tp_hit/sl_hit/force_close/strategy_exit
       -> _send_user_exit_alert(... alert_kind='tp_hit' ...)
          -> notifications.send -> if False: WARN with alert_kind + tg_id + market_id

  bot/handlers/my_trades.py / trades.py (manual close)
    -> monitoring/alerts.alert_user_manual_close
       -> _send_user_exit_alert(... alert_kind='manual_close' ...)
          -> (same WARN path)

  core/event_bus subscribers (services/notification_service.py)
    -> _send_safe(... event_name='position.opened' / 'position.closed' / ...)
       -> notifications.send -> if False: WARN with event_name + tg_id

  domain/execution/paper.py::execute / services/trade_engine/...
    -> services/trade_notifications/notifier._send(... event=ENTRY/TP_HIT/... )
       -> notifications.send -> if False: WARN with notification_event + market_id + tg_id

Paper close idempotency (unchanged; only test coverage added):

  paper.close_position(position, exit_price, exit_reason)
    async with conn.transaction():
      updated = UPDATE positions SET status='closed' ...
                WHERE id=$1 AND status='open' AND user_id=$5
      if updated is None:
        return {exit_reason: 'already_closed'}        # idempotent no-op
      ledger.credit_in_conn(...)                      # atomic with UPDATE
    audit.write(...)                                   # only on happy branch
    portfolio_snapshots.write_snapshot(user_id)        # only on happy branch
```

---

## 3. Files Created / Modified

Created:
- `projects/polymarket/crusaderbot/tests/test_warp53_reliability_hardening.py`
- `projects/polymarket/crusaderbot/reports/forge/warp53-reliability-hardening.md`

Modified:
- `projects/polymarket/crusaderbot/notifications.py` — added `_wait_telegram(wait_base)` honouring `RetryAfter.retry_after` (capped at 30s); bumped `stop_after_attempt` 3 → 4; constants `_MAX_RETRY_AFTER_SECONDS=30.0` and `_MAX_SEND_ATTEMPTS=4` exposed for tests.
- `projects/polymarket/crusaderbot/services/trade_notifications/notifier.py` — `_send` now checks `notifications.send` bool return and logs WARNING `trade_notification.delivery_dropped` tagged with `notification_event` + `market_id` + `telegram_user_id` on False; `_edit_or_resend` fallback `notifications.send` now checks bool return and logs WARNING `animated_status.fallback_send_dropped` on False.
- `projects/polymarket/crusaderbot/services/notification_service.py` — `_send_safe` now checks `notifications.send` bool return and logs WARNING `notification_service: delivery_dropped` tagged with `event_name` + `telegram_user_id` on False.
- `projects/polymarket/crusaderbot/monitoring/alerts.py` — new `_send_user_exit_alert(...)` helper consolidates the bool-return WARNING path; all 7 `alert_user_*` functions (tp_hit / sl_hit / force_close / strategy_exit / manual_close / market_expired / close_failed) now route through it tagged by `alert_kind`. The `alert_user_close_failed` warning that previously fired unconditionally is now gated on delivery success so logs no longer claim "delivered" for a dropped message.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — WARP-53 status added; KNOWN ISSUES untouched outside scope.
- `projects/polymarket/crusaderbot/state/WORKTODO.md` — P0 "Telegram notification reliability" and "Paper trading consistency (PnL, positions, ledger)" checked.
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — lane closure entry appended.

No schema changes. No risk constant changes. No new external dependency. No phase folders.

---

## 4. What Is Working

Evidence (file:line + test result for every claim):

- `_wait_telegram` honours `RetryAfter.retry_after`. See `notifications.py:48-83`. Pinned by `test_send_honours_retry_after_on_429` — first RetryAfter(retry_after=2) on attempt 1 produces a recorded wait >= 2.0 s, second attempt succeeds.
- RetryAfter wait is capped at 30 s. See `notifications.py:30-34`. Pinned by `test_send_caps_retry_after_at_30_seconds` — RetryAfter(retry_after=600) is clamped; no recorded wait exceeds 30.
- Attempt budget exhaustion still returns False and logs ERROR. See `notifications.py:79-89` (unchanged structurally; max attempts now 4). Pinned by `test_send_returns_false_after_attempt_budget_exhausted` — 4 consecutive RetryAfters cause `bot.send_message` await_count == 4 and the permanent-failure ERROR is captured by caplog.
- Notifier per-event WARNING on False. See `services/trade_notifications/notifier.py:_send` (modified). Pinned by `test_notifier_logs_warning_when_send_returns_false` — WARNING contains `tp_hit`, `mkt-abc`, `4242`.
- Notification-service per-event WARNING on False. See `services/notification_service.py:_send_safe` (modified). Pinned by `test_notification_service_logs_warning_when_send_returns_false` — WARNING contains `position.opened`, `5151`.
- Monitoring alert per-kind WARNING on False. See `monitoring/alerts.py:_send_user_exit_alert` (new). Pinned by `test_alert_user_tp_hit_logs_warning_when_dropped` — WARNING contains `tp_hit`, `9999`, `mkt-xyz`.
- Paper close idempotency under double-call. See `domain/execution/paper.py:97-145` (unchanged code). Pinned by `test_paper_close_position_idempotent_under_double_close` — second call returns `exit_reason='already_closed'`, snapshot writer await_count == 1, audit writer await_count == 1, no further `conn.execute` after the first close.

Test run output (cloud-environment hermetic suite, post-cffi install):

```
projects/polymarket/crusaderbot/tests/test_warp53_reliability_hardening.py
.......                                                                  [100%]
7 passed in 0.26s

projects/polymarket/crusaderbot/tests/test_notifications_gate.py
projects/polymarket/crusaderbot/tests/test_trade_notifications.py
projects/polymarket/crusaderbot/tests/test_portfolio_snapshots_writer.py
............................                                             [100%]
28 passed in 0.34s
```

`py_compile` passes on all four modified production files and the new test file.

`test_exit_watcher.py` collection currently fails in this sandbox with `ModuleNotFoundError: eth_account` — a pre-existing env limitation (live-trading dep missing from the cloud runner), NOT a regression: no exit_watcher code was modified in this lane.

---

## 5. Known Issues

- Wait-strategy cap of 30 s means we may still drop messages on a sustained Telegram-side stall longer than the combined attempt window (~1 capped 30 s + ~3 sub-10 s waits). Trade-off: protecting caller latency vs maximizing delivery. The cap is exposed as `_MAX_RETRY_AFTER_SECONDS` for future tuning. Not a regression — old behaviour dropped on ANY 429 with retry_after > 8 s.
- `notifications.send` still logs only the LAST exception's repr on permanent failure; per-attempt diagnostics (which attempts hit RetryAfter vs NetworkError) are not surfaced. Operationally adequate for the WARP-53 gate (drops are auditable per-event upstream now), but a richer per-attempt log could be a future enhancement.
- WARP-53 §1 mentioned a `continue_on_error` audit. No such pattern exists in the notification path (grep returned only documentation references). Requirement satisfied vacuously — flagged here so it does not look glossed over.
- `bot/handlers/my_trades.py:close_confirm_cb` and `bot/handlers/trades.py:close_confirm_cb` both wrap `paper_exec.close_position` in a try/except that catches `Exception` and surfaces a UI message — they do not retry. This is consistent with the existing manual-close UX and not in WARP-53 scope (the user gets immediate feedback either way). Out of scope for this lane; revisit if WARP-54 surfaces a real failure mode.
- The new `test_paper_close_position_idempotent_under_double_close` exercises serial double-call, not true concurrency (asyncio.gather two close calls). Serial double-call provably reproduces the same DB row-state transition that concurrent calls produce because the guard is a single SQL UPDATE WHERE status='open'; concurrent calls would interleave at the DB level which is precisely where the guard fires. Stronger concurrency coverage is left for a hermetic asyncpg integration test in a future lane.

---

## 6. What Is Next

Suggested next step: WARP🔹CMD review + merge. Tier STANDARD → WARP•SENTINEL is NOT required per AGENTS.md routing.

Post-merge sequence:
1. Fly.io redeploy required (no migration; only Python code changed). After deploy, real-world 429 episodes should show a `Telegram send permanently failed` ERROR rate drop and the per-event WARNING `*.delivery_dropped` becoming the canonical signal for dropped notifications.
2. Observability check (recommended, optional): grep production logs over a 24h window for `delivery_dropped` — establishes baseline rate before WARP-54 builds on top.

Follow-up lanes (NOT this lane):
- WARP-54 (#1253) — closed beta hardening. Explicitly gated on WARP-53 merge (issue body line). Covers: dedup guard, exit_watcher restart recovery, user_id isolation matrix, parse_mode=HTML fallback for BadRequest, API timeout behaviour. Per WARP🔹CMD direction this session, WARP-54 starts in a separate session after WARP-53 merges.
- Optional: raise `_MAX_RETRY_AFTER_SECONDS` if production telemetry shows sustained 429s being permanently dropped. Currently 30 s is the conservative choice.
- Optional: structlog-ify the `notifications.send` ERROR log so it carries `attempts`, `last_error_type`, and `chat_id` as fields rather than a single repr line.

---

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : 429 RetryAfter is honoured by notifications.send wait strategy; every per-event call site (notifier._send, _edit_or_resend, _send_safe, all 7 alert_user_*) logs a context-tagged WARNING on bool=False; paper.close_position double-close returns already_closed with zero additional ledger / audit / snapshot writes
Not in Scope      : Live trading paths, WebTrader, UI changes, new features, ledger schema, manual close UX, restart recovery (WARP-54), user_id isolation (WARP-54), parse_mode=HTML fallback (WARP-54)
Suggested Next    : WARP🔹CMD review
