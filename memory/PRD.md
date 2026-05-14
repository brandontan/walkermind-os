# CrusaderBot Telegram UX/UI V6 Redesign

## Project
WalkerMind OS — CrusaderBot Telegram Bot
Path: /app/projects/polymarket/crusaderbot/

## Goal
Redesign Telegram-native UX for CrusaderBot to be clean, simple, premium, and beginner-friendly.
Inspired by Kreo Polymarket, PolyBot Copytrade, Photon/Banana Gun style simplicity.

## Architecture
- Custom python-telegram-bot (PTB) v21+ abstraction layer
- Bot: bot/app.py, handlers/, keyboards/, menus/
- Domain: domain/ (presets, risk, positions, execution)
- DB: asyncpg + PostgreSQL
- Scheduler: APScheduler background jobs

## User Personas
- New traders: need clear onboarding, no jargon
- Returning traders: fast dashboard access
- Operators: admin access via settings hub

## Core Requirements (Static)
1. SIMPLE > COMPLEX — fewer buttons, clear actions
2. FUNCTIONAL > BEAUTIFUL — every button must work
3. TELEGRAM-NATIVE — reply keyboard, not dashboard clutter
4. PERSISTENT KEYBOARD — always visible at bottom
5. BEGINNER-FRIENDLY — explain what each thing does

## What's Been Implemented (V6 — 2026-05-14)

### Main Menu (bot/keyboards/__init__.py)
- Changed from 6 buttons to 5 buttons
- V6: [Auto Trade] [Portfolio] / [Settings] [Insights] / [Stop Bot]
- Removed: Dashboard, Referrals, Help from main menu

### Menu Routes (bot/menus/main.py)
- Updated MAIN_MENU_ROUTES for V6 buttons
- Added: Insights → pnl_insights_command, Stop Bot → emergency_root
- Removed: Dashboard, Referrals, Help routes from reply keyboard

### Onboarding (bot/handlers/onboarding.py)
- New clean welcome text per spec:
  🚀 Welcome to CrusaderBot
  📑 Mode: PAPER / 🟢 Status: Ready
  ├ Engine: Active / ├ Capital: $X / └ Trading: Disabled
- Removed "Get Started" friction step — keyboard established immediately
- New users get main_menu() reply keyboard on first /start
- set_onboarding_complete called immediately (no ConversationHandler state)

### Dashboard (bot/handlers/dashboard.py)
- Shortened to: Bot status, Balance, Mode, Today PnL, Open positions count
- Removed: Equity tree, W/L stats, Pulse section, verbose blocks
- Added: open_positions count to _fetch_stats query

### Auto Trade / Presets (bot/handlers/presets.py, keyboards/__init__.py)
- Fixed: _MVP_LABELS/_MVP_DESCRIPTIONS now keyed by preset key (signal_sniper etc.)
- Beginner-friendly descriptions with Risk level, Capital %, behavior
- Picker shows full description for each strategy
- Confirmation: "Balanced activated" instead of "Strategy Updated"
- Updated _MENU_BUTTONS_CUSTOMIZE to V6 labels

### Settings Hub (bot/keyboards/settings.py, bot/handlers/settings.py)
- Removed: Premium stub, Live Gate stub from hub keyboard
- Removed: Dead stubs replaced with functional handlers
- Added: Mode, Wallet, Notifications (with toggle), Health (actual bot status)
- Fixed: Profile stub no longer opens settings again (loop fix)
- Health: shows actual bot status + recent job_runs from DB
- Admin: routes to actual admin_root (operator only)

### Portfolio (bot/handlers/positions.py)
- Removed enterprise language: "premium monitoring is standing by" gone
- New: "No open positions. Use Auto Trade to start."
- Uses open_positions from _fetch_stats

### Insights (bot/handlers/pnl_insights.py)
- Removed duplicate: weekly_section concatenation removed
- Shows only format_insights (no repeated weekly breakdown)
- Empty state: "Not enough data yet. Need at least 3 closed trades."

### Tests Updated
- test_phase5d_grid_menu_split.py — V6 button set, 5 buttons, new routes
- test_ux_overhaul.py — V6 layout, wallet in hub, auto_trade route
- test_preset_system.py — updated text assertions for new V6 copy

## Test Status
- 109 tests passing (test_phase5d + test_ux_overhaul + test_preset_system)
- Pre-existing failures in test_trade_notifications, test_referral_system (pytest-asyncio issue, not related to V6)

## Prioritized Backlog (P0/P1/P2)

### P0 (Critical)
- None outstanding for V6 UX

### P1 (Important)  
- Persistent keyboard: returning users (new device edge case) — send main_menu() on returning /start
- Notifications toggle: persist to user_settings.notifications_on column (may not exist yet)
- Copy Trade menu: not accessible from main V6 menu (moved to Settings or as /copytrade command)

### P2 (Nice to Have)
- Live bot testing with token: 8795145097:AAGQW9yIOswG3GMmvTByfLpHPnLWU08DOk8
- /help command update for V6 button labels
- Referral accessible via /referral command only (not in main settings hub)

## Files Changed (V6)
- bot/keyboards/__init__.py — main_menu, dashboard_kb, portfolio_kb, mvp_auto_trade_kb
- bot/menus/main.py — MAIN_MENU_ROUTES
- bot/handlers/onboarding.py — welcome text, flow
- bot/handlers/dashboard.py — _build_text shorter, open_positions count
- bot/handlers/presets.py — descriptions, _MVP_LABELS/_MVP_DESCRIPTIONS, regex
- bot/keyboards/settings.py — settings_hub_kb groups
- bot/handlers/settings.py — health functional, notifications toggle, profile fix
- bot/handlers/positions.py — portfolio text
- bot/handlers/pnl_insights.py — no duplicate weekly
- bot/keyboards/presets.py — wizard_done_kb label
- bot/handlers/copy_trade.py — _MENU_BUTTONS V6 labels
- tests/test_phase5d_grid_menu_split.py — V6 assertions
- tests/test_ux_overhaul.py — V6 assertions
- tests/test_preset_system.py — V6 text assertions
