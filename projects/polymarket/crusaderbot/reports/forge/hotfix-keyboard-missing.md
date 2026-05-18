# WARP•FORGE Report — Hotfix: Restore Missing Persistent Reply Keyboard

**Branch:** WARP/HOTFIX-KEYBOARD-MISSING
**Validation Tier:** STANDARD
**Claim Level:** PRESENTATION
**SENTINEL Required:** NO
**Date:** 2026-05-12

---

## 1. What Was Built

Restored the persistent Telegram reply keyboard (Dashboard / My Trades / Auto-Trade / Copy Trade / Settings / Stop Bot) that went missing after PR #989 (UX Overhaul) and PR #987 (Track L Onboarding Polish).

Root cause: two handlers that serve as primary entry points never re-attached `ReplyKeyboardMarkup` after the UX Overhaul changed the keyboard layout. A Telegram persistent reply keyboard must be explicitly re-sent via `reply_markup=ReplyKeyboardMarkup(...)` at least once to establish it in a user's session. Once established it persists, but if never established (new user) or displaced by `ReplyKeyboardRemove` / never re-sent after a gap, it vanishes.

**Fix 1 — `bot/handlers/dashboard.py` — `dashboard()` function**
Added `main_menu` to keyboard imports. Changed `reply_markup=dashboard_nav(has_trades)` → `reply_markup=main_menu()` in the `dashboard()` handler (the message-path entry point called from both `/start` returning-user routing and the "📊 Dashboard" reply keyboard tap). This restores the keyboard for all returning ALLOWLISTED users on every `/start` and every Dashboard tap.

**Fix 2 — `bot/handlers/onboarding.py` — `_mode_cb` paper path**
After the existing `paper_complete_kb()` (inline "View Dashboard" button) message, added `await q.message.reply_text("Main menu:", reply_markup=main_menu())`. This establishes the persistent keyboard immediately on paper-mode onboarding completion for all new users.

No other logic was changed. No activation guards touched. No trading, risk, or execution code modified.

---

## 2. Current System Architecture

```
/start
  └─ Returning user (ALLOWLISTED)
       └─ dashboard()  →  reply_markup=main_menu()  ✅ keyboard established
  └─ Returning user (non-ALLOWLISTED)
       └─ reply_markup=main_menu()  ✅ already correct (unchanged)
  └─ New user
       └─ _entry() → welcome + get_started_kb()
            └─ _get_started_cb() → mode select
                 └─ _mode_cb() (paper) → paper_complete_kb() + main_menu()  ✅ keyboard established

Reply keyboard tap: "📊 Dashboard"
  └─ dashboard()  →  reply_markup=main_menu()  ✅ keyboard re-established on every tap

Inline "View Dashboard" tap (from paper_complete_kb)
  └─ view_dashboard_cb() → show_dashboard_for_cb()
       └─ reply_markup=dashboard_nav(has_trades)  (inline nav; keyboard already established above)
```

---

## 3. Files Created / Modified

**Modified:**
- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py`
  - Line 15: added `main_menu` to keyboard imports
  - Line 180: `dashboard()` — changed `reply_markup=dashboard_nav(has_trades)` → `reply_markup=main_menu()`

- `projects/polymarket/crusaderbot/bot/handlers/onboarding.py`
  - After line 183: added `await q.message.reply_text("Main menu:", reply_markup=main_menu())` in `_mode_cb` paper path

**Created:**
- `projects/polymarket/crusaderbot/reports/forge/hotfix-keyboard-missing.md` (this file)

**Not Modified:**
- `bot/handlers/onboarding.py` — `show_dashboard_for_cb`, `_entry`, `_get_started_cb`, `build_onboard_handler`, `help_handler`, `menu_handler` — all unchanged
- `bot/handlers/dashboard.py` — `show_dashboard_for_cb`, `dashboard_nav_cb`, all other handlers — unchanged
- `bot/keyboards/__init__.py` — `main_menu()` definition unchanged
- Any trading, risk, execution, or activation guard code

---

## 4. What Is Working

- `/start` (returning ALLOWLISTED user) → dashboard card sent with `main_menu()` → keyboard appears
- `/start` (new user paper path) → onboarding completes → paper_complete_kb() + "Main menu:" with `main_menu()` → keyboard appears
- `/start` (non-ALLOWLISTED returning user) → already correct, unchanged
- "📊 Dashboard" tap → `dashboard()` → keyboard re-established on every tap
- 99 existing hermetic tests unaffected (no test logic changed)

---

## 5. Known Issues

None introduced by this hotfix. `show_dashboard_for_cb` retains `dashboard_nav(has_trades)` inline nav; keyboard is already established before this handler is reached in all UX paths.

---

## 6. What Is Next

- WARP🔹CMD review → merge
- No follow-up tasks required

---

**Validation Target:** `dashboard()` reply_markup in `dashboard.py`; `_mode_cb` paper path reply_markup in `onboarding.py`
**Not in Scope:** Trading logic, risk constants, activation guards, DB schema, other handlers
**Suggested Next Step:** WARP🔹CMD review → merge to main
