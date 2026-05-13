# WARP•FORGE Report — telegram-lightweight-tree-ui-hotfix

**Date:** 2026-05-13
**Branch:** claude/telegram-lightweight-tree-ui-MNQ8w
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Telegram message formatting + keyboard persistence only
**Not in Scope:** Copy Wallet feature, execution logic, risk logic, DB, routing, callback contract changes, live trading guard

---

## 1. What was built

Final Lightweight Tree UI hotfix for the CrusaderBot Telegram UX.
Replaced all heavy terminal-rail patterns (`│` standalone lines, `├──`, `└──` long-arm trees)
with a compact one-level tree style (`├ item`, `└ item`) across every affected screen.
Added nav row to preset_picker keyboard to prevent user trapping on the Auto Trade screen.

---

## 2. Current system architecture

No architecture changes. UX surface only — Telegram message text templates updated in-place.
Routing, callback_data, handler registration, and execution guards are all unchanged.

---

## 3. Files created / modified

Modified (8 files):

- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py`
  `_build_text()`: removed 5 standalone `│\n` separators; replaced nested PnL/WL block with flat `├`/`└` items under 💹 Today; Auto Trade and Portfolio sections now use `├ key: value` / `└ key: value` pattern.

- `projects/polymarket/crusaderbot/bot/handlers/presets.py`
  `_preset_picker_text()`: replaced `│   ├──` / `│   │   └──` nested block with flat `├`/`└` preset list.
  `_preset_confirm_text()`: removed `│\n` rails; flat single-level Strategy / Configuration / Mode sections.
  `_preset_status_text()`: removed `│\n` rails; flat single-level Strategy / Performance / Config sections.
  `_step1_text()`, `_step2_text()`, `_step3_text()`, `_step5_text()`: removed `│\n` and `├──`/`└──` heavy arms throughout wizard steps.

- `projects/polymarket/crusaderbot/bot/handlers/positions.py`
  `show_portfolio()`: removed 4 standalone `│\n` separators; flat `├ key: value` / `└ key: value` tree.
  `show_positions()`: replaced `├──`/`└──` long-arm connectors with `├`/`└`; removed `│` opening line; removed indented-branch variable.

- `projects/polymarket/crusaderbot/bot/handlers/settings.py`
  `_hub_text()`: removed 2 standalone `│\n` separators; Account section uses `├ Mode:` / `└ Tier:`.
  `_capital_text()`: removed 2 standalone `│\n` separators; inline `├ Balance:` / `└ ⚠` pattern.

- `projects/polymarket/crusaderbot/bot/handlers/signal_following.py`
  `_build_signals_screen()`: replaced `├──`/`└──` connectors with `├`/`└` in following and available trees; removed 4 standalone `│\n` separator lines.

- `projects/polymarket/crusaderbot/bot/handlers/onboarding.py`
  `_WELCOME_TEXT`: removed 3 standalone `│\n` lines; Current Mode block uses `├`/`└` items; Setup block uses `├`/`└` items.
  `_PAPER_COMPLETE_TEXT`: removed 3 standalone `│\n` lines; Commands block uses `├`/`└` items.

- `projects/polymarket/crusaderbot/bot/keyboards/presets.py`
  `preset_picker()`: added `nav_row("dashboard:main")` to the returned InlineKeyboardMarkup so users can navigate back from the Auto Trade preset picker without being trapped.
  Import updated: `from . import grid_rows, nav_row`.

- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py`
  No changes — `dashboard_kb()` already matches the required persistent keyboard layout.

---

## 4. What is working

- All 8 files compile cleanly (`py_compile` + `compileall` — zero errors).
- No standalone `│` characters remain in any user-facing string literal across touched files.
- No `├──` or `└──` long-arm patterns remain in any user-facing string literal.
- All `callback_data` values are unchanged — routing contract intact.
- No new CallbackQueryHandler or CommandHandler registrations introduced.
- `preset_picker()` now includes Back / Home / Refresh nav row, resolving the trapping regression.
- Dashboard, Portfolio, Auto Trade, Settings, Signal Feeds, and Onboarding screens all render with max one-level tree depth.
- Persistent ReplyKeyboard (`main_menu()`) unaffected — all affected handlers send `InlineKeyboardMarkup` which does not displace the existing reply keyboard.

---

## 5. Known issues

- `noop:refresh` callback in `nav_row()` has no registered handler; it is pre-existing behaviour not introduced by this lane.
- Onboarding parse_mode is MarkdownV2; `├` and `└` are not MarkdownV2 special characters and require no escaping — confirmed safe.

---

## 6. What is next

WARP🔹CMD review required. Tier: STANDARD. Merge when satisfied.
After merge: `WARP/notifications-paper-wire` to wire `notify_order_filled()` into paper executor remains deferred next priority.
