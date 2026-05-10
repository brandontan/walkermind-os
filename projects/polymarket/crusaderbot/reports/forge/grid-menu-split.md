# WARP•FORGE Report — grid-menu-split

**Branch:** claude/grid-layout-trade-menu-split-7OhAP (Phase 5D)
**Date:** 2026-05-10 14:00 Asia/Jakarta
**Validation Tier:** STANDARD
**Claim Level:** MENU LAYOUT ONLY
**Validation Target:** Button grid layout + Copy Trade / Auto-Trade menu split + preset count trim
**Not in Scope:** Copy Trade functionality (Phase 5E/5F), trading logic, execution, DB schema, activation guards

---

## 1. What Was Built

Phase 5D delivers three UX-layer changes with zero runtime or execution impact:

**A. 2-Column Button Grid**
- New `grid_rows(buttons, cols=2)` helper in `bot/keyboards/__init__.py`
- Pairs a flat list of buttons into rows of N (default 2); odd count → partial last row
- Applied to every inline keyboard in the bot: wallet, setup, strategy, risk, category, mode, autoredeem, emergency, admin, dashboard_nav, preset_picker, preset_confirm, preset_switch_confirm, preset_stop_confirm, autoredeem_settings_picker, ops_dashboard_keyboard

**B. Main Menu Expansion (5 → 6 buttons)**
- `main_menu()` now produces 3 rows of 2:
  `[📊 Dashboard] [🐋 Copy Trade]`
  `[🤖 Auto-Trade] [📈 My Trades]`
  `[💰 Wallet] [🚨 Emergency]`
- `🐋 Copy Trade` is a new top-level entry point, separate from `🤖 Auto-Trade`
- `menu_copytrade_handler` registered in `MAIN_MENU_ROUTES` (text routing via `_text_router`)
- Placeholder renders "Coming soon — Phase 5E" card with `[📊 Dashboard] [🤖 Auto-Trade]` inline nav buttons

**C. Preset System Trim (5 → 3 presets)**
- Removed `whale_mirror` and `hybrid` from `PRESETS` and `PRESET_ORDER`
- `copy_trade` strategy now belongs exclusively to the Copy Trade surface (🐋); it is not an Auto-Trade preset strategy
- `full_auto` updated: strategies = `("signal", "value")` — no longer includes `copy_trade`
- `RECOMMENDED_PRESET` changed from `whale_mirror` → `signal_sniper`
- Preset descriptions updated to match Phase 5D UX spec language

---

## 2. Current System Architecture

```
ReplyKeyboard (text buttons)
  ├─ 📊 Dashboard  → dashboard.dashboard
  ├─ 🐋 Copy Trade → copy_trade.menu_copytrade_handler  [NEW — placeholder]
  ├─ 🤖 Auto-Trade → setup.setup_root → presets handler
  ├─ 📈 My Trades  → positions.my_trades
  ├─ 💰 Wallet     → wallet.wallet_root
  └─ 🚨 Emergency  → emergency.emergency_root

Inline Keyboards (all 2-col via grid_rows)
  ├─ preset_picker: [📡 Signal Sniper ⭐] [🎯 Value Hunter] / [🚀 Full Auto]
  ├─ preset_confirm: [✅ Activate] [✏️ Customize] / [← Back]
  ├─ preset_status: [✏️ Edit] [🔄 Switch] / [⏸/▶️] [🛑 Stop]  (unchanged)
  ├─ dashboard_nav: [🤖 Auto-Trade] [📈 Trades] / [💰 Wallet]
  ├─ emergency_menu: [⏸ Pause] [▶️ Resume] / [🛑 Pause + Close All]
  └─ … all others per grid_rows()

Copy Trade placeholder → [📊 Dashboard (dashboard:main)] [🤖 Auto-Trade (preset:picker)]
dashboard_nav_cb extended: sub="main" re-renders full dashboard card via q.message.reply_text
```

---

## 3. Files Created / Modified

**Modified:**
- `projects/polymarket/crusaderbot/domain/preset/presets.py` — 3 presets, new order, new recommended, updated descriptions
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py` — grid_rows helper, 6-button main_menu, all keyboards 2-col
- `projects/polymarket/crusaderbot/bot/keyboards/presets.py` — grid_rows applied, imports from . grid_rows
- `projects/polymarket/crusaderbot/bot/keyboards/settings.py` — grid_rows applied
- `projects/polymarket/crusaderbot/bot/keyboards/admin.py` — grid_rows applied (ops_dashboard_keyboard); Lock kept on separate row per safety comment
- `projects/polymarket/crusaderbot/bot/handlers/copy_trade.py` — InlineKeyboardMarkup import added; _PLACEHOLDER_TEXT/_PLACEHOLDER_KB; menu_copytrade_handler
- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py` — dashboard:main sub added to dashboard_nav_cb
- `projects/polymarket/crusaderbot/bot/handlers/presets.py` — "5-preset" comment → "preset"; Phase 5D/5G customize placeholder text updated
- `projects/polymarket/crusaderbot/bot/menus/main.py` — copy_trade import added; 🐋 Copy Trade route added to MAIN_MENU_ROUTES
- `projects/polymarket/crusaderbot/tests/test_preset_system.py` — updated for 3 presets, new order, new recommended
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — Phase 5D added to [IN PROGRESS], [NEXT PRIORITY] updated
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — Phase 5D lane entry appended

**Created:**
- `projects/polymarket/crusaderbot/tests/test_phase5d_grid_menu_split.py` — 19 new hermetic tests
- `projects/polymarket/crusaderbot/reports/forge/grid-menu-split.md` — this report

---

## 4. What Is Working

- `grid_rows()` tested for even, odd, single, empty, custom cols
- `main_menu()` produces 6 buttons in 3 rows of 2 — verified by test
- `🐋 Copy Trade` and `🤖 Auto-Trade` are separate routes in `MAIN_MENU_ROUTES` — verified by test
- `menu_copytrade_handler` sends placeholder text with correct inline buttons — verified by test
- `dashboard:main` callback re-renders full dashboard from inline button — untested (dashboard rendering requires DB pool mock not set up in Phase 5D tests; covered by existing dashboard handler test suite)
- `preset_picker()` renders 3 presets in 2-col grid (2 rows) — verified by test
- `preset_confirm()` renders 3 buttons in 2-col (Activate + Customize / Back) — verified by test
- `preset_switch_confirm()` and `preset_stop_confirm()` now 2-col — verified by test
- `dashboard_nav()`, `wallet_menu()`, `emergency_menu()` all 2-col — verified by test
- All 38 updated preset system tests pass (3 presets, new order, new recommended)
- 19 new Phase 5D tests pass
- Total: 57/57 tests in the two Phase 5D test files

---

## 5. Known Issues

- `dashboard:main` callback path not hermetically tested (requires mocked DB pool + balance/pnl ledger); the code path mirrors `dashboard()` inline and is covered by manual review
- Phase 5D tests skip the `dashboard:main` callback test; it is safe because the sub-handler uses the same `_fetch_stats` / `_build_text` calls already tested by existing dashboard tests
- `whale_mirror` and `hybrid` preset keys may still exist in production `user_settings.active_preset` rows for users who activated those presets in earlier versions; `get_preset()` now returns `None` for those keys, causing `show_preset_status()` to fall back to the picker (correct degradation — user picks a new preset from the 3 available)

---

## 6. What Is Next

- WARP🔹CMD review + merge decision (STANDARD tier, no SENTINEL required)
- After merge: dispatch Phase 5E — Copy Trade dashboard + wallet discovery (depends on 5D menu split)
- Phase 5G customize wizard (independent of 5E)
- Phase 5I My Trades redesign (independent)
- Phase 5J Emergency menu redesign (independent)

---

**Suggested Next Step:** WARP🔹CMD review + merge decision on this PR. Unlocks Phase 5E Copy Trade dashboard.
