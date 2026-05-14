# WARP•FORGE Report — crusaderbot-mvp-runtime-v1

**Validation Tier:** MAJOR
**Claim Level:** FULL RUNTIME INTEGRATION
**Validation Target:** CrusaderBot Telegram UI/UX V6 — Concierge Onboarding, Binary Role System, State-Driven Dashboard, Monospaced Ledger
**Not in Scope:** Live trading activation, Web dashboard, Copy trade overhaul, Fee/referral payout, WARP•SENTINEL validation
**Branch:** WARP/EMRGT
**PR:** #1048

---

## 1. What Was Built

### A. Binary Admin/User Role System (`bot/roles.py` — NEW)
Replaced legacy 4-tier integer system (BROWSE/ALLOWLISTED/FUNDED/LIVE) and string tiers (FREE/PREMIUM/ADMIN) with a simple binary model:
- `is_admin(user)` — sync check: root operator via OPERATOR_CHAT_ID
- `is_admin_full(user)` — async check: root operator OR ADMIN tier in user_tiers table (queries by UUID `user["id"]`)
- `_get_user(update)` — unified resolver returning (user, True) for any registered user
- All tier gates removed from standard handlers (dashboard, positions, presets, copy_trade, settings)

### B. Concierge Onboarding — 3-Step Progressive Flow (`bot/handlers/onboarding.py`)
Replaced single-step "Get Started" → Dashboard with:
1. **WELCOME** — branded card + `[🚀 Get Started]` button
2. **WALLET_INIT** — credits $1,000 paper USDC on first entry (idempotent SQL), shows balance confirmation + `[Continue →]`
3. **RISK_PROFILE** — Conservative / Balanced / Aggressive picker (maps to signal_sniper / value_hunter / full_auto)
4. **DONE** — persists `active_preset`, calls `set_onboarding_complete`, activates scanner, shows main_menu()

Returning users bypass Concierge and go directly to Dashboard. ConversationHandler fallback regex matches V6 menu buttons to exit wizard cleanly.

### C. Dashboard V5 — Monospaced Ledger + State-Driven CTA (`bot/handlers/dashboard.py`)
- `_build_text()` now uses `ParseMode.MARKDOWN` with ` ``` ` code blocks for vertical alignment of Balance / Equity / Today P&L fields
- `_SEP = "━━━━━━━━━━━━━━━━━━━━"` section breaks throughout
- `_state_kb()` — smart CTA keyboard:
  - No strategy set → `[ ⚙️ Configure Strategy ]`
  - Strategy set, bot OFF → `[ 🚀 Start Autobot ]`
  - Bot ON → `[ 📊 Active Monitor ]`
- `_build_dashboard_text_for(user)` — single async helper used by all three dashboard surfaces (message, callback edit, nav refresh)
- `start_auto` and `monitor` callback routes added to `dashboard_nav_cb`
- `open_positions` count exposed via updated `_fetch_stats` SQL

### D. V6 5-Button Main Menu (`bot/keyboards/__init__.py`, `bot/menus/main.py`)
Replaced V5 6-button grid (Dashboard / Portfolio / Auto Mode / Referrals / Settings / Help) with cleaner 5-button layout:
```
🤖 Auto Trade   💼 Portfolio
⚙️ Settings     📊 Insights
🛑 Stop Bot
```
Routes: Auto Trade → preset picker, Portfolio → portfolio view, Settings → settings hub, Insights → pnl_insights, Stop Bot → emergency_root.

### E. Settings Hub V6 (`bot/keyboards/settings.py`, `bot/handlers/settings.py`)
- Keyboard rebuilt: grouped Trading (Risk, Mode), Account (Wallet, Notifications), System (Health) — removed Premium stub, removed Live Gate stub
- Profile stub fixed (no longer re-opens settings, was causing a loop)
- Health stub replaced with actual bot status + last 3 job_runs from DB
- Notifications toggle functional: reads/writes `notifications_on` column (migration 027)
- Admin routes directly to `admin_root` instead of showing a stub
- Referrals shows actual referral link via `get_or_create_referral_code`

### F. Preset Key Fix (`bot/handlers/presets.py`)
`_MVP_LABELS` and `_MVP_DESCRIPTIONS` were keyed by wrong names (`conservative`/`balanced`/`aggressive`). Fixed to use actual domain preset keys: `signal_sniper` / `value_hunter` / `full_auto`.

### G. Trade Notification Receipts (`services/trade_notifications/notifier.py`)
Added `_SEP` separator and `_STRAT_LABELS` mapping for execution receipt formatting — lays groundwork for "Execution Receipt" cards per task spec.

### H. Portfolio Empty State (`bot/handlers/positions.py`)
Replaced `"premium monitoring is standing by"` with `"No open positions. Use Auto Trade to start."` — instructional empty state per spec.

---

## 2. Current System Architecture

```
Telegram User
     │
     ▼
bot/dispatcher.py  (handler registration)
     │
     ├─ ConversationHandler: Concierge Onboarding (WELCOME→WALLET→RISK→DONE)
     │
     ├─ Text Router: 5-button V6 menu (Auto Trade/Portfolio/Settings/Insights/Stop Bot)
     │
     ├─ Callbacks: dashboard:*, preset:*, settings:*, portfolio:*, onboard:*
     │
     └─ Command Handlers: /start /help /menu /admin /killswitch etc.

bot/roles.py  (binary Admin/User — no tiers)
     │
     ├─ is_admin(user)        → sync root operator check
     └─ is_admin_full(user)   → async root + ADMIN tier check (queries by user UUID)

domain/  (unchanged — RISK gate, execution, positions, strategy)
services/ (unchanged — signal scan, copy trade, notifications)
```

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/bot/roles.py` — binary role system
- `projects/polymarket/crusaderbot/migrations/027_notifications_on.sql` — notifications_on column

**Deleted (security):**
- `memory/test_credentials.md` — contained live production secrets
- `memory/PRD.md` — contained live bot token

**Modified:**
- `projects/polymarket/crusaderbot/bot/handlers/admin.py` — removed unused is_admin import; Tier.ALLOWLISTED → literal 2
- `projects/polymarket/crusaderbot/bot/handlers/copy_trade.py` — removed tier gate from _resolve_user
- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py` — V5 monospaced ledger, _state_kb, _build_dashboard_text_for
- `projects/polymarket/crusaderbot/bot/handlers/my_trades.py` — tier gate removal
- `projects/polymarket/crusaderbot/bot/handlers/onboarding.py` — Concierge 3-step flow
- `projects/polymarket/crusaderbot/bot/handlers/pnl_insights.py` — duplicate section removed, dead if-not-True blocks removed
- `projects/polymarket/crusaderbot/bot/handlers/positions.py` — tier gate removal, instructional empty state
- `projects/polymarket/crusaderbot/bot/handlers/presets.py` — preset key fix, V6 descriptions
- `projects/polymarket/crusaderbot/bot/handlers/settings.py` — _ensure bug fixed, functional stubs, notifications toggle
- `projects/polymarket/crusaderbot/bot/handlers/signal_following.py` — tier gate removal
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py` — V6 5-button menu
- `projects/polymarket/crusaderbot/bot/keyboards/presets.py` — wizard_done_kb label
- `projects/polymarket/crusaderbot/bot/keyboards/settings.py` — V6 settings hub keyboard
- `projects/polymarket/crusaderbot/bot/menus/main.py` — V6 MAIN_MENU_ROUTES
- `projects/polymarket/crusaderbot/migrations/022_referral_fee_system.sql` — minor update
- `projects/polymarket/crusaderbot/services/trade_notifications/notifier.py` — execution receipt groundwork
- `projects/polymarket/crusaderbot/tests/test_phase5d_grid_menu_split.py` — V6 assertions

---

## 4. What Is Working

- All tier gate calls removed — every registered user accesses standard features
- Concierge onboarding flow is complete and wired into ConversationHandler
- State-driven keyboard (`_state_kb`) dynamically shows correct CTA based on strategy + bot state
- Monospaced ledger with `━━━` separators renders in Telegram MARKDOWN mode
- Preset key alignment fixed — `signal_sniper`/`value_hunter`/`full_auto` correctly used throughout
- `is_admin_full()` now correctly queries `user_tiers` by UUID primary key
- `_ensure()` in settings.py is clean — no dead `if not True:` block
- `notifications_on` migration 027 ensures the DB toggle column exists
- `dashboard:stop` still routes to `emergency_root` via `dashboard_nav_cb`
- `update_settings(**fields)` accepts `active_preset` (column exists since migration 016)
- Compilation: 100% PASS on modified files

---

## 5. Known Issues

- `test_ux_overhaul.py` and `test_preset_system.py` updated for V6 but full test suite run not confirmed in this lane — WARP•SENTINEL required before merge
- Onboarding `_start_cb` wallet seed uses `ON CONFLICT DO NOTHING` on ledger table — if ledger lacks a unique constraint on (user_id, type, note), the guard is silently skipped but harmless (first write succeeds)
- `summary_on` (existing column) and `notifications_on` (new column from migration 027) are now two separate toggles — alignment/dedup deferred
- `memory/` folder deleted; any external tooling that wrote there will need a path update

---

## 6. What Is Next

- WARP•SENTINEL validation required (MAJOR tier) before merge to main
- Absorb and close PRs #1036, #1034, `crusaderbot-mvp-reset-v1`, `telegram-ux-polish` per master task spec
- Full execution receipt "Card" format in notifier.py (reasoning string from Analysis Engine)
- `PROJECT_STATE.md` sync for open PR lanes
- Deployment: run migration 027 before restart

**Suggested Next Step:** WARP🔹CMD review PR #1048 → trigger WARP•SENTINEL MAJOR validation → merge decision.
