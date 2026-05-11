# WARP•FORGE Report — CrusaderBot Premium PNL Insights UX

**Branch:** `WARP/crusaderbot-premium-pnl-insights`
**Issue:** #963
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Date:** 2026-05-11 Asia/Jakarta

---

## 1. What was built

A new on-demand `/insights` command and a `insights:refresh` callback surface that
surfaces rich PNL analytics from the existing closed `positions` table. No DB schema
migration required. The insight panel shows: win rate, profit factor, average win /
average loss, best and worst trade with market title, current win/loss streak, and a
7-day P&L summary. The surface is Telegram Markdown compatible and follows the existing
dashboard / my_trades UX patterns.

Additionally, the `/insights` surface is wired into the existing navigation:
- `📊 Insights` button added to `dashboard_nav` when `has_trades=True`.
- `📊 Insights` button added to `my_trades_main_kb` nav row.
- `dashboard:insights` sub-handler added to `dashboard_nav_cb`.

All changes are presentation-only. No execution, risk, capital, or guard values touched.

## 2. Current system architecture

Data flow for `/insights`:
1. `pnl_insights_command` (CommandHandler) / `insights_cb` (CallbackQueryHandler) calls
   `_fetch_insights(user_id)`.
2. `_fetch_insights` acquires one DB connection and runs 4 queries against `positions`
   and `markets` (all read-only):
   - Aggregate stats (`fetchrow`): total_closed, wins, losses, gross_wins, gross_losses,
     best_pnl, worst_pnl, avg_win, avg_loss, trades_7d, pnl_7d.
   - Best trade market title (`fetchrow`): JOIN on `markets`, ORDER BY pnl_usdc DESC LIMIT 1.
   - Worst trade market title (`fetchrow`): same, ORDER BY pnl_usdc ASC LIMIT 1.
   - Streak source (`fetch`): last 25 closed pnl_usdc values DESC by closed_at.
3. `_compute_streak(pnl_values)` computes direction and length from the streak list.
4. `format_insights(data)` renders the Telegram Markdown message (pure function).
5. Reply is sent with `insights_kb()` (Refresh + Dashboard buttons).

The `dashboard:insights` sub in `dashboard_nav_cb` delegates entirely to the same
`_fetch_insights` / `format_insights` / `insights_kb` trio via a deferred import
to match the existing pattern in dashboard.py (autotrade_toggle_pending_confirm uses
the same style).

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/bot/handlers/pnl_insights.py`
- `projects/polymarket/crusaderbot/tests/test_pnl_insights.py`
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-premium-pnl-insights.md`

Modified:
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py` — added `insights_kb()`;
  updated `dashboard_nav()` to include `📊 Insights` button (4th button, has_trades only).
- `projects/polymarket/crusaderbot/bot/keyboards/my_trades.py` — added `📊 Insights`
  button to `my_trades_main_kb` nav row alongside Full History and Dashboard.
- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py` — added `dashboard:insights`
  sub-case in `dashboard_nav_cb` (deferred import of pnl_insights).
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — imported `pnl_insights_h`;
  registered `CommandHandler("insights", ...)` and `CallbackQueryHandler(pattern=r"^insights:")`.

State updates (this same commit):
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- 15 hermetic tests green under pytest 9.0.2 / pytest-asyncio 0.23:
  - `format_insights`: empty state, wins-only (∞ profit factor), losses-only, mixed,
    best/worst PnL string rendering.
  - `_compute_streak`: empty, win streak, loss streak, direction break, break-even-as-loss.
  - Keyboard structure: `insights_kb` buttons, `dashboard_nav` Insights presence/absence,
    `my_trades_main_kb` Insights link.
- Pure functions (`format_insights`, `_compute_streak`) are fully decoupled from DB and
  Telegram runtime — testable with no mocks.
- Dispatcher registers `/insights` command before the free-text fallback and registers
  `insights:` callback before Phase 5I my_trades handlers.
- Tier gate (ALLOWLISTED = Tier 2+) enforced on both command and callback paths.
- Paper-mode posture unchanged; no activation guards touched.

## 5. Known issues

- None introduced by this lane.
- Inherited: all deferred items from PROJECT_STATE.md [KNOWN ISSUES] are unchanged.

## 6. What is next

- WARP🔹CMD review of this PR.
- No WARP•SENTINEL required (STANDARD tier, NARROW INTEGRATION, no risk/execution
  surface, no activation guard changes).
- Future enhancements (NOT in this lane): weekly digest, chart image attachments,
  per-strategy breakdown, referral/share/fee prep — queued for later Week 2 lanes.

---

## Metadata

- **Validation Target:** `bot/handlers/pnl_insights.py` handler + formatter + streak
  logic; `bot/keyboards/__init__.py` `insights_kb` + `dashboard_nav` update;
  `bot/keyboards/my_trades.py` nav row update; `bot/handlers/dashboard.py`
  `dashboard:insights` sub; `bot/dispatcher.py` command + callback registration;
  `tests/test_pnl_insights.py` 15 hermetic tests.
- **Not in Scope:** activation guard flips, live trading enablement, CLOB order placement,
  risk/capital/execution logic, DB schema migration, referral/share/fee implementation.
- **Suggested Next Step:** WARP🔹CMD merge decision after auto-PR review.
  State files updated in this same PR per CLAUDE.md state-sync rule.

## Activation Guards (unchanged — DO NOT TOUCH)

- `ENABLE_LIVE_TRADING=false`
- `EXECUTION_PATH_VALIDATED=false`
- `CAPITAL_MODE_CONFIRMED=false`
- `RISK_CONTROLS_VALIDATED=false`
- `USE_REAL_CLOB=false`
