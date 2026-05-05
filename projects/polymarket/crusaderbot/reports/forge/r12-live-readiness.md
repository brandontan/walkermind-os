# WARP•FORGE Report — R12 Live Readiness Batch

Branch: `WARP/CRUSADERBOT-R12-LIVE-READINESS`
Validation Tier: **STANDARD**
Claim Level: **NARROW INTEGRATION**
Validation Target: live opt-in checklist gate logic, live-to-paper fallback trigger + audit + notification, daily P&L summary message correctness + scheduler registration.
Not in Scope: real Telegram delivery in test (mocked), activation guard flips (checklist only validates, never sets), P&L calendar web view (Phase 5+), per-strategy P&L breakdown (Phase 5+), live trading execution path (gated separately).
Suggested Next Step: WARP🔹CMD review (STANDARD — no SENTINEL), then merge.

---

## 1. What was built

Three R12 production-readiness items shipped together. None of them touch capital execution logic — they sit on top of the existing risk gate, router, and notification surface.

### (1) Live Opt-In Checklist
`domain/activation/live_checklist.evaluate(user_id)` runs eight gates in fixed order. The result records both individual outcomes and a flat `failed_gates` list so the Telegram surface can render a numbered fix list without re-deriving order. Every evaluation writes one `audit.log` row (`live_checklist_evaluated`) with the full outcome snapshot.

| # | Gate | Source of truth |
|---|---|---|
| 1 | EXECUTION_PATH_VALIDATED | `Settings.EXECUTION_PATH_VALIDATED` env flag |
| 2 | CAPITAL_MODE_CONFIRMED | `Settings.CAPITAL_MODE_CONFIRMED` env flag |
| 3 | ENABLE_LIVE_TRADING | `Settings.ENABLE_LIVE_TRADING` env flag |
| 4 | active_subaccount_with_deposit | `wallets` row + ≥1 row in `deposits` with `confirmed_at IS NOT NULL` |
| 5 | strategy_configured | `user_settings.strategy_types` non-empty |
| 6 | risk_profile_configured | `user_settings.risk_profile` non-empty |
| 7 | two_factor_setup_complete | `system_settings` key `2fa_enabled:{user_id}` (default OFF — gate fails closed until 2FA infra ships) |
| 8 | operator_allowlist_approved | `users.access_tier >= 4` (Tier 4 = Live auto-trade per migrations/001_init.sql) |

`/live_checklist` Telegram command (`bot/handlers/activation.py`) renders pass/fail. On the dashboard's auto-trade toggle, when the user is currently OFF and `user_settings.trading_mode='live'`, the toggle now arms `ctx.user_data['awaiting']='confirm_live_autotrade'` and returns a "type CONFIRM to proceed" prompt. Only the case-sensitive string `CONFIRM` flips `users.auto_trade_on=true` — anything else cancels.

### (2) Live-to-Paper Fallback
`domain/execution/fallback.trigger(user_id, reason)` flips `user_settings.trading_mode='live' → 'paper'`, writes one `audit.log` row, and sends one Telegram message per affected user. Idempotent — already-paper users are no-ops with no audit / notify noise. Open positions are intentionally NOT closed (close router still routes live for live-mode positions; only NEW signals are deflected to paper).

Wired into existing error handlers:

| Trigger condition | Wire site |
|---|---|
| [1] CLOB non-recoverable error | `domain/execution/router.py` — after `LivePostSubmitError` is caught and re-raised |
| [1b] Live guard unset mid-flight | `domain/execution/router.py` — when `LivePreSubmitError` carries `ENABLE_LIVE_TRADING=false` |
| [2a] Risk gate kill-switch halt | `domain/risk/gate.py` — gate step 1, when `ctx.trading_mode='live'` |
| [2b] Risk gate drawdown halt | `domain/risk/gate.py` — gate step 6, when `ctx.trading_mode='live'` |
| [3] Operator kill switch lock | `domain/ops/kill_switch.set_active(action='lock')` — single SQL UPDATE flips every live user to paper inside the lock transaction |
| [4] Live guard unset (per-flight) | covered by [1b] |

System-wide cascade is exposed via `fallback.trigger_all_live_users(reason)` which performs a single `UPDATE user_settings ... RETURNING` and then loops only over the affected rows for audit / notify. No per-user round trip on the DB hot path.

### (3) Daily P&L Summary
`jobs/daily_pnl_summary.run_job` registered in `scheduler.setup_scheduler()` as a cron job at `hour=23 minute=0` anchored to the scheduler's `Asia/Jakarta` timezone. Per-user message format:

```
📊 Daily Summary — YYYY-MM-DD
Realized P&L  : +$X.XX / -$X.XX
Unrealized P&L: +$X.XX / -$X.XX
Fees paid     : $X.XX
Open positions: N
Exposure      : X.X%
Mode          : PAPER / LIVE
```

Realized = today's `ledger` rows of type `trade_close` + `redeem` (Asia/Jakarta day boundary via `date_trunc('day', NOW() AT TIME ZONE 'Asia/Jakarta')`). Fees = abs sum of `ledger` type `fee` for today (stored as negative debits, surfaced as positive paid amount). Unrealized = sum over open positions of `size_usdc * ret_pct` using the same YES/NO formulas the close engine uses. Exposure = open exposure / wallet balance × 100.

Opt-in toggle uses `system_settings` key `daily_summary_off:{user_id}` (default = ON; absence of row → enabled). `/summary_off` and `/summary_on` Telegram commands flip the flag. Migration-free.

Per-user failures (build error, Telegram send false) are caught and counted; the batch always finishes and returns `{sent, skipped_disabled, skipped_no_telegram, failed, total_users, date}`. The existing R12f scheduler listener already writes one `job_runs` row per cron tick — this job inherits that bookkeeping without duplicate code.

---

## 2. Current system architecture

```
                ┌──────────────────────────────────────────────┐
                │  Telegram surface (bot/handlers/activation)  │
                │   /live_checklist  /summary_on  /summary_off │
                └────┬───────────────┬───────────────┬─────────┘
                     │               │               │
        evaluate()   │   set_summary_enabled()       │
                     ▼               │               │
   ┌────────────────────────┐        │               │
   │ domain/activation/     │        │  build/run/format
   │   live_checklist       │        │       ▼
   │   (8 gates → audit)    │        │ ┌────────────────────────┐
   └────────────────────────┘        │ │  jobs/daily_pnl_summary │
                                     │ │  cron 23:00 Jakarta     │
                                     │ │  + system_settings opt-in│
                                     │ └────────────────────────┘
   ┌────────────────────────┐        │
   │ domain/execution/      │        │
   │   fallback             │◄───────┴───── notifications.send
   │   trigger / cascade    │
   └────────────────────────┘
        ▲          ▲          ▲             ▲
        │          │          │             │
   router    risk gate    kill_switch     dashboard.autotrade_toggle_cb
   (post-    (kill+      (lock cascade)    (CONFIRM dialog before live ON)
   submit /  drawdown)
   pre-submit)
```

Surgical edits, not rewrites. Each call site forwards a single user id and a controlled `reason` string; the central fallback module owns the persistence + audit + notify side effects.

---

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/domain/activation/__init__.py`
- `projects/polymarket/crusaderbot/domain/activation/live_checklist.py`
- `projects/polymarket/crusaderbot/domain/execution/fallback.py`
- `projects/polymarket/crusaderbot/jobs/__init__.py`
- `projects/polymarket/crusaderbot/jobs/daily_pnl_summary.py`
- `projects/polymarket/crusaderbot/bot/handlers/activation.py`
- `projects/polymarket/crusaderbot/tests/test_live_checklist.py`
- `projects/polymarket/crusaderbot/tests/test_fallback.py`
- `projects/polymarket/crusaderbot/tests/test_daily_pnl_summary.py`
- `projects/polymarket/crusaderbot/tests/test_activation_handlers.py`
- `projects/polymarket/crusaderbot/reports/forge/r12-live-readiness.md`

Modified:
- `projects/polymarket/crusaderbot/domain/execution/router.py` — fallback trigger on post-submit error and on `ENABLE_LIVE_TRADING=false` pre-submit error.
- `projects/polymarket/crusaderbot/domain/risk/gate.py` — fallback trigger at kill-switch (step 1) and drawdown (step 6) halts when user was in live mode.
- `projects/polymarket/crusaderbot/domain/ops/kill_switch.py` — system-wide live→paper cascade inside the lock transaction.
- `projects/polymarket/crusaderbot/scheduler.py` — registered `daily_pnl_summary` cron job at 23:00 Jakarta.
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — registered `/live_checklist`, `/summary_on`, `/summary_off`; threaded `activation.text_input` into `_text_router` ahead of menu routing.
- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py` — `autotrade_toggle_cb` defers to `activation.autotrade_toggle_pending_confirm` when the toggle would enable live mode.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — R12 lanes moved to COMPLETED, NEXT PRIORITY updated.
- `projects/polymarket/crusaderbot/state/WORKTODO.md` — three R12 items checked off.
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — appended one entry for this lane.

---

## 4. What is working

- 56 new tests across the four new test files; all 331 crusaderbot tests pass (was 305 before this lane). No existing tests modified.
- `live_checklist.evaluate` returns the right `failed_gates` for every isolation case: each individual gate failing alone, all-three-env failing, partial mixes, all-pass.
- `fallback.trigger` is idempotent on already-paper users (no audit, no notify); writes one audit row per real flip; survives a Telegram failure without raising.
- `fallback.trigger_all_live_users` writes one audit row per affected user and reports `{"changed": N}`.
- `daily_pnl_summary.run_once` correctly skips opt-out users, skips users with no Telegram id, swallows per-user failures, and returns aggregate stats.
- `format_summary` renders signed amounts (+ / − / zero), exposure as a one-decimal percent, and the mode label uppercase.
- Scheduler registration test confirms a `cron` trigger with `hour=23 minute=0` exists under `JOB_ID="daily_pnl_summary"`.
- LIVE auto-trade toggle is gated by typed `CONFIRM` (case-sensitive). Wrong reply or paper-mode toggle short-circuits cleanly.

---

## 5. Known issues

- Gate [7] (`two_factor_setup_complete`) reads from `system_settings` rather than a real 2FA store. Until self-serve 2FA infra ships, the operator must manually flip `system_settings.value='true'` on key `2fa_enabled:{user_id}` for any user permitted to go live. Fail-closed default keeps live trading locked until that explicit operator action.
- Realized P&L line uses the `ledger` table as the source. Fee rows are stored as negative debits (`ledger.amount_usdc < 0`); the summary surfaces them as a separate positive `Fees paid` line, but `Realized P&L` deliberately excludes fees so users see gross trading P&L. If WARP🔹CMD wants net P&L instead, it is a one-line change in `_fetch_user_summary_row`.
- The cascade UPDATE in `kill_switch.set_active(action='lock')` flips `trading_mode='paper'` for all currently-live users in the same transaction as the user-disable UPDATE. It does NOT emit a per-user audit row — the existing `kill_switch_history` row plus the per-user audit emitted on a NEXT signal scan together cover the trail. If WARP🔹CMD wants explicit per-user audit on the lock event, switch the lock path to call `fallback.trigger_all_live_users` instead of the inline UPDATE.
- `notifications.daily_summary_enabled` is stored as an opt-OUT flag in `system_settings` (key `daily_summary_off:{user_id}`) rather than a column on `user_settings` — chosen so the lane stays migration-free per the done criteria. If a future lane wants the toggle in the user settings menu UI, it can wrap `set_summary_enabled`.
- **Pre-existing NO-side P&L bug surfaced during review (NOT introduced here, NOT fixed here):** `domain/execution/paper.close_position`, `domain/execution/live.close_position`, and `domain/execution/exit_watcher._return_pct` all use a YES-perspective complement formula for NO positions (`comp_entry = 1 - entry`, `ret = (comp_exit - comp_entry) / comp_entry`). However, `domain/positions/registry.update_current_price` and the strategy candidate builders persist `entry_price` / `current_price` side-specifically (NO market price for NO rows). This means realized `positions.pnl_usdc` for closed NO positions is sign-inverted, exit-watcher TP/SL trips on NO positions are inverted, and `bot/handlers/positions.py:_unrealized_pnl` also has the wrong NO branch. The new daily summary uses the side-specific direct formula `(current - entry) / entry` so unrealized P&L on NO positions is reported correctly here, but realized P&L (read from the upstream `positions.pnl_usdc`) inherits the codebase bug for NO closes. This needs a dedicated lane covering close engines + exit watcher + bot/handlers/positions; out of scope for R12 live readiness.

---

## 6. What is next

- WARP🔹CMD review (STANDARD tier — SENTINEL not required).
- After merge: `state/PROJECT_STATE.md` reflects R12 final-deployment unblocked pending P3c/P3d completion. Lane closure summary written to CHANGELOG.
- Self-serve 2FA module (out of scope here) is the natural follow-up so gate [7] reads a real source instead of the operator-flip key.
- Per-strategy P&L breakdown in the daily summary (Phase 5+).
- P&L calendar web view (Phase 5+).
