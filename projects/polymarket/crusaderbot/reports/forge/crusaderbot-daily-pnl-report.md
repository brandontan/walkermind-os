# WARP•FORGE Report — Fast Track Track E: Daily P&L Report

**Branch:** `WARP/crusaderbot-daily-pnl-report`
**Issue:** #960
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Date:** 2026-05-11 Asia/Jakarta

---

## 1. What was built

Fast Track Track E extends the existing R12 daily P&L summary (jobs/daily_pnl_summary.py) with paper-mode activity counts and an explicit no-trade empty state. Operators and paper-mode users now receive a daily Telegram summary at 23:00 Asia/Jakarta that reports realized/unrealized P&L, fees, opened/closed trade counts with W/L breakdown, open positions, exposure, and trading mode. Days with no activity render a compact one-line empty state instead of all-zero noise.

## 2. Current system architecture

The summary continues to dispatch via APScheduler (`scheduler.setup_scheduler`) using the same `daily_pnl_summary.JOB_ID` cron (hour=23, minute=0, anchored to `settings.TIMEZONE`). `run_job → run_once` iterates `users` filtered by `access_tier >= 2`, honors the `daily_summary_off:{user_id}` opt-in toggle, and pushes through `notifications.send`. Per-user errors are swallowed and counted; the batch never short-circuits.

Aggregation flow (`_fetch_user_summary_row`) now executes one additional SQL call against `positions` that returns four COUNT(\*) FILTER columns scoped to `mode='paper'`: `opened_today`, `closed_today`, `wins_today`, `losses_today`. R12's realized/unrealized/fees/exposure queries are preserved verbatim — the existing operator-facing totals retain their unfiltered semantics.

Formatter (`format_summary`) takes the four new counts as keyword args with default 0 (back-compat for R12 callers). When `opened_today == 0 and closed_today == 0 and open_count == 0`, the formatter returns a compact two-line "No paper trades today" body; otherwise it renders the extended eight-line summary with the new `Trades opened` and `Trades closed (W:X L:Y)` lines.

## 3. Files created / modified (full repo-root paths)

Modified:

- `projects/polymarket/crusaderbot/jobs/daily_pnl_summary.py` — added paper-mode counts query, extended `format_summary` signature with `opened_today`/`closed_today`/`wins_today`/`losses_today` (defaulted to 0), added no-trade empty-state branch, updated module docstring.
- `projects/polymarket/crusaderbot/tests/test_daily_pnl_summary.py` — added 8 new tests (no-trade compact form, no-trade skipped when open position present, W/L breakdown rendering, counts aggregation via fetchrow, no-trade end-to-end via build_summary_for_user, mode='paper' filter assertion on counts query, scheduler `run_job` callable wiring, run_job → run_once callback path), updated 2 R12 tests (`test_format_summary_zero_amounts_when_activity_present`, `test_format_summary_negative_amounts`, `test_build_summary_handles_missing_balance_zero_exposure`) so they pin down the full-format path instead of accidentally hitting the new no-trade branch.

State updates (next chunk):

- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/ROADMAP.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

Not modified: `scheduler.py` (R12 wiring already registers `daily_pnl_summary.run_job` at 23:00 Asia/Jakarta — scope of Track E is scheduler-callback wiring verification, not re-wiring).

## 4. What is working

- 26 daily-P&L tests + smoke suite (28 total) green under pytest 9.0.3 / pytest-asyncio 1.3.0.
- Paper-mode counts query executes via `fetchrow` in the same pool acquire as the existing R12 reads — no extra connection overhead.
- `format_summary` no-trade branch keeps the Telegram payload short on idle days; otherwise the eight-line body renders with W/L breakdown.
- Backward compatibility: every R12 caller of `format_summary` continues to work because the four new keyword args default to 0. Existing scheduler registration, opt-in toggle, recipient filter, and Telegram send path are unchanged.
- Scheduler-callback test asserts `job.func is dp.run_job` so a future refactor that swaps the registered callable will break the test instead of silently shipping.
- mode='paper' assertion test pins the counts query so live trades cannot leak into the paper summary breakdown after activation guards flip.

## 5. Known issues

- None introduced by Track E.
- Inherited from R12 (out of scope): the `system_settings`-backed opt-out flag still uses an off-flag convention (`true` = OFF) for migration-free deployment.
- The `notifications.send` retry chain is unchanged; transient Telegram failures still log at ERROR and count toward `failed` without aborting the batch.

## 6. What is next

- WARP🔹CMD review of this PR.
- No WARP•SENTINEL required (STANDARD tier, NARROW INTEGRATION, no risk/execution surface touched, no activation guard changes).
- Future enhancements (NOT in this lane): per-strategy P&L breakdown, weekly digest, premium chart attachments — all queued for Fast Track Week 2 UX pack.

---

## Metadata

- **Validation Target:** `jobs/daily_pnl_summary.py` aggregation + formatter changes; `tests/test_daily_pnl_summary.py` coverage.
- **Not in Scope:** activation guard flips, live trading enablement, CLOB order placement, risk/capital/execution logic, premium chart UX, scheduler re-wiring.
- **Suggested Next Step:** WARP🔹CMD merge decision after auto-PR review. State files updated in this same PR per CLAUDE.md state-sync rule.

## Activation Guards (unchanged — DO NOT TOUCH)

- `ENABLE_LIVE_TRADING=false`
- `EXECUTION_PATH_VALIDATED=false`
- `CAPITAL_MODE_CONFIRMED=false`
- `RISK_CONTROLS_VALIDATED=false`
- `USE_REAL_CLOB=false`
