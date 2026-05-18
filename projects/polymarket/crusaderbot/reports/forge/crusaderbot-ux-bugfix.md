# WARP•FORGE REPORT — crusaderbot-ux-bugfix

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: Telegram bot UX layer — callbacks, monitor view, startup alerts, admin tooling
Not in Scope: Live trading, strategy logic, DB schema changes, execution pipeline

---

## 1. What Was Built

Five UX bug fixes in the CrusaderBot Telegram bot layer:

- **BUG 1A** — `autotrade_toggle_cb`: After toggling auto-trade, the handler now refreshes the dashboard in-place via `edit_message_text` with `_state_kb`, replacing a bare `reply_text` with no keyboard (dead-end).
- **BUG 1B** — `dashboard:trades` callback: Both the "no trades" path and the trades list path now include `nav_row("dashboard:portfolio")` so users can navigate back.
- **BUG 1C** — `insights_kb()`: Added `nav_row("dashboard:main")` as a third row so the insights surface has Back/Home/Refresh navigation.
- **BUG 2** — `dashboard:monitor`: Replaced the plain dashboard refresh with a dedicated `_build_monitor_text()` view showing scanner state (scanned/published/last tick) and today's portfolio snapshot (open positions, today PnL).
- **BUG 3** — `alert_startup()`: Added `/tmp` file-based cooldown (`_STARTUP_LOCK`) to suppress repeated startup alerts within 10 minutes on the same Fly machine instance. File-based lock survives crash-restarts; a new machine deploy starts fresh and alerts once.
- **BUG 4** — Admin `/resetonboard {telegram_user_id}` command: resets `onboarding_complete=False`, `auto_trade_on=False`, `active_preset=NULL`, `strategy_types=NULL`. Guard: `_is_admin_user` (operator OR ADMIN tier). Audit log entry written. Button "🔄 Reset Onboarding" added to `admin_menu()`.
- **BUG 5** — Curly quote audit: zero Unicode curly quotes found in `bot/`. No changes needed.

---

## 2. Current System Architecture

No architecture changes. Changes are confined to:
- `bot/handlers/dashboard.py` — callback handler logic
- `bot/handlers/admin.py` — new admin command
- `bot/keyboards/__init__.py` — keyboard definitions
- `bot/dispatcher.py` — command registration
- `monitoring/alerts.py` — startup alert suppression

Pipeline posture unchanged: DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING.
`ENABLE_LIVE_TRADING` guard untouched. PAPER ONLY mode unchanged.

---

## 3. Files Created / Modified

Modified (full repo-root paths):

- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py`
- `projects/polymarket/crusaderbot/bot/handlers/admin.py`
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py`
- `projects/polymarket/crusaderbot/bot/dispatcher.py`
- `projects/polymarket/crusaderbot/monitoring/alerts.py`

Created:

- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-ux-bugfix.md` (this file)

---

## 4. What Is Working

- `python3 -m compileall` — PASS (zero errors)
- `ruff check` — PASS (all checks passed)
- Curly quote grep — PASS (zero hits)
- All five callback paths now return `reply_markup` (no dead-end screens)
- `_build_monitor_text` correctly imports `get_scanner_state` from `...jobs.market_signal_scanner` and `get_pool` from `...database` (already in module scope)
- `alert_startup` file-based lock is best-effort (exception-safe on both read and write)
- `/resetonboard` requires admin/operator role, writes audit log, handles user-not-found gracefully
- `admin_menu()` now has 4 buttons (2×2 grid via `grid_rows`)

---

## 5. Known Issues

- `_build_monitor_text` uses `user["id"]` (UUID) for DB queries. If `user["id"]` is not set (edge case during session failure), the DB call will raise. This matches existing patterns in the codebase — no regression introduced.
- The `/tmp` startup lock is not shared across Fly machines in multi-instance deployments. Each machine gets its own independent 10-minute cooldown. This is correct behavior per the task specification.

---

## 6. What Is Next

WARP🔹CMD review required.
Source: `projects/polymarket/crusaderbot/reports/forge/crusaderbot-ux-bugfix.md`
Tier: STANDARD

Suggested next steps:
- Deploy to Fly.io (paper mode) and verify Active Monitor shows real scanner stats
- Test `/resetonboard` with paper test user walk3r69 to confirm concierge re-triggers on `/start`
- Observe startup alert behavior across two rapid bot restarts (expect single alert)
