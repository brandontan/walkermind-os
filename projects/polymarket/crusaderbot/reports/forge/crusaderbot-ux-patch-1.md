# WARP•FORGE Report — crusaderbot-ux-patch-1

Branch: WARP/CRUSADERBOT-UX-PATCH-1
Date: 2026-05-15 13:30 Asia/Jakarta
Validation Tier: MINOR
Claim Level: NARROW INTEGRATION
Validation Target: Telegram UX — startup message leak guard + bot-ON ReplyKeyboard layout fix
Not in Scope: execution engine, risk gate, activation guards, DB schema, live trading path

---

## 1. What Was Built

Two targeted fixes on top of PR #1049 (crusaderbot-mvp-runtime-ux):

**Fix 1 — Startup message leak guard**
Added an explicit `if settings.OPERATOR_CHAT_ID:` guard around the `🟢 CrusaderBot up` startup notification in `main.py`. The send was already unconditionally targeting `OPERATOR_CHAT_ID`, but without the guard a misconfigured environment (OPERATOR_CHAT_ID unset) would silently skip the send rather than potentially misdirecting it. The guard makes admin-only intent explicit and prevents future regression. `monitoring/alerts.py:_dispatch()` already has its own guard; `admin.py` has `_is_operator()` checks — no changes needed in those files.

**Fix 2 — Bot-ON ReplyKeyboard layout**
Corrected `main_menu(auto_on=True)` from a stale 5-button (Dashboard+Auto-Trade / Portfolio+My Trades / Emergency) layout to the correct 4-button MVP layout:
- Row 0: [📊 Active Monitor]
- Row 1: [💼 Portfolio] [⚙️ Settings]
- Row 2: [🚨 Emergency]

Updated `MAIN_MENU_ROUTES` to reflect the new route set (Active Monitor → dashboard, removed Dashboard/Auto-Trade/My Trades as top-level routes). Removed unused `my_trades` import from `menus/main.py`. Updated `_MENU_BUTTONS` in `copy_trade.py` (ConversationHandler wizard-exit detection set) to match current button labels — the old set had stale labels from a prior UI version ("🤖 Auto Trade" without hyphen, "📊 Insights", "🛑 Stop Bot"). Updated all 74 hermetic tests in the two affected test files to match new layout.

---

## 2. Current System Architecture

Telegram UX routing follows a two-layer model:
- **ReplyKeyboard** (`bot/keyboards/__init__.py:main_menu()`) — persistent 3-state nav bar shown to user; drives `MAIN_MENU_ROUTES` text dispatch
- **InlineKeyboard** — context-specific sub-menus rendered per screen (dashboard, settings, etc.)

State machine for `main_menu()`:
- `auto_on=False, strategy_key=None` → Configure Strategy / Portfolio+Settings / Emergency (4 buttons)
- `auto_on=False, strategy_key=<key>` → Start Autobot / Portfolio+Settings / Emergency (4 buttons)
- `auto_on=True` → Active Monitor / Portfolio+Settings / Emergency (4 buttons)

Stop Bot lives inside the inline Auto-Trade sub-menu only; it is not a ReplyKeyboard surface. The inline `dashboard_nav()` keyboard already used "📊 Active Monitor" as the CTA — the ReplyKeyboard is now consistent with it.

---

## 3. Files Created / Modified

Modified (full repo-root paths):
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py` — `main_menu(auto_on=True)` row layout corrected (5-button → 4-button, 1+2+1)
- `projects/polymarket/crusaderbot/bot/menus/main.py` — MAIN_MENU_ROUTES updated; module docstring updated; unused `my_trades` import removed
- `projects/polymarket/crusaderbot/bot/handlers/copy_trade.py` — `_MENU_BUTTONS` updated to current button labels
- `projects/polymarket/crusaderbot/main.py` — explicit `if settings.OPERATOR_CHAT_ID:` guard added to startup notification send
- `projects/polymarket/crusaderbot/tests/test_phase5d_grid_menu_split.py` — 9 test functions updated/renamed for new layout
- `projects/polymarket/crusaderbot/tests/test_ux_overhaul.py` — 3 test functions updated/replaced

Created: none

---

## 4. What Is Working

- `python3 -m compileall` — 4 source files compile cleanly, no errors
- `ruff check` — all checks passed
- `pytest tests/test_phase5d_grid_menu_split.py tests/test_ux_overhaul.py` — 74 passed in 0.74s
- `main_menu(auto_on=True)` renders correct 3-row 4-button layout
- `MAIN_MENU_ROUTES` contains exactly: Active Monitor, Portfolio, Emergency, Start Autobot, Configure Strategy, Settings
- `_MENU_BUTTONS` in copy_trade.py matches the current ReplyKeyboard surface labels
- Startup notification unconditionally targets OPERATOR_CHAT_ID; guard prevents misdirection on misconfiguration

---

## 5. Known Issues

- Full test suite (1405 tests) was not run in this session due to missing `web3` system dependency in the CI environment; the 74 hermetic UX tests relevant to this patch all pass. This is pre-existing and unrelated to this patch.
- `monitoring/alerts.py:schedule_alert()` fire-and-forget path is not unit-tested in this patch (out of scope; existing behavior unchanged).

---

## 6. What Is Next

- WARP🔹CMD review required.
- Deploy WARP/CRUSADERBOT-UX-PATCH-1 to Fly.io (PAPER ONLY — activation guards remain OFF).
- Apply migration 027 (notifications_on) before production deploy if not already applied.
- Keep production PAPER ONLY until explicit owner live activation decision.

---

Suggested Next Step: WARP🔹CMD review → merge → Fly.io deploy (paper mode).
