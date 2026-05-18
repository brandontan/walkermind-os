# WARP•FORGE Report — crusaderbot-mvp-reset-v1

Branch: WARP/crusaderbot-mvp-reset-v1
Date: 2026-05-14 03:37
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: Telegram MVP UX reset — onboarding, dashboard, auto trade, portfolio, settings, risk profile
Not in Scope: Copy Wallet, Insights, Signal Feeds, analytics, premium, execution logic, trading engine, DB schema, risk backend
Suggested Next: WARP🔹CMD review

---

## 1. What Was Built

MVP UX reset for CrusaderBot Telegram interface. Replaced accumulated multi-layer menu architecture with a clean, working 5-screen MVP. Old experimental UI surfaces archived in-place (deprecated, not reachable from main user flow).

**Changes summary:**
- Onboarding: single "Get Started" CTA, clean welcome text with paper mode status block, no mode selection step, no internal telemetry in message text
- Main navigation: 7-button reply keyboard → 5-button MVP (removed Signal Feeds, Insights)
- Dashboard: simplified 3-section text (Bot / Account / Today), fixed inline keyboard (no smart CTA)
- Auto Trade: Conservative / Balanced / Aggressive labels mapped to signal_sniper / value_hunter / full_auto preset keys
- Portfolio: simplified text (Balance / Performance / Positions), removed Chart/Insights/Trades buttons
- Settings: hub reduced to Notifications + Risk only, removed Profile/Premium/Referrals/Health/Live Gate/Wallet
- Risk Profile: new clean MVP screen with Conservative/Balanced/Aggressive + Back/Home
- All underlying handlers, callbacks, and execution logic untouched

---

## 2. Current System Architecture (Relevant Slice)

```
/start
  └── new user  → MVP Welcome + "🚀 Get Started" → onboard complete → Dashboard
  └── returning → Dashboard (if ALLOWLISTED) or waitlist message

Reply Keyboard (main_menu):
  🏠 Dashboard  💼 Portfolio
  🤖 Auto Trade  ⚙️ Settings
  🛑 Stop Bot

Dashboard (dashboard_kb):
  🤖 Auto Trade  💼 Portfolio
  ⚙️ Settings    🛑 Stop Bot
  🔄 Refresh

Auto Trade (mvp_auto_trade_kb):
  📡 Conservative → preset:pick:signal_sniper
  🎯 Balanced     → preset:pick:value_hunter
  🚀 Aggressive   → preset:pick:full_auto
  ⬅ Back  🏠 Home

Portfolio (portfolio_kb):
  📋 Positions  🔄 Refresh
  ⬅ Back  🏠 Home

Settings (settings_hub_kb):
  🔔 Notifications  ⚖️ Risk
  ⬅ Back  🏠 Home

Risk Profile (mvp_risk_kb):
  📡 Conservative → set_risk:conservative
  🎯 Balanced     → set_risk:balanced
  🚀 Aggressive   → set_risk:aggressive
  ⬅ Back  🏠 Home
```

---

## 3. Files Created / Modified

**Modified:**
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py` — main_menu MVP (5 buttons), dashboard_kb (no cta_btn), portfolio_kb MVP, +mvp_auto_trade_kb, +mvp_risk_kb; legacy versions archived as _legacy_*
- `projects/polymarket/crusaderbot/bot/keyboards/onboarding.py` — get_started_kb MVP (single CTA); legacy functions archived as _legacy_*
- `projects/polymarket/crusaderbot/bot/keyboards/settings.py` — settings_hub_kb MVP (2 items); legacy function archived as _legacy_settings_hub_kb
- `projects/polymarket/crusaderbot/bot/menus/main.py` — removed Signal Feeds + Insights routes; 5-button routing
- `projects/polymarket/crusaderbot/bot/handlers/onboarding.py` — MVP welcome text, single ONBOARD_WELCOME state, Get Started → complete → dashboard; removed ONBOARD_MODE state
- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py` — MVP 3-section text, dashboard_kb() no cta_btn, removed _smart_cta
- `projects/polymarket/crusaderbot/bot/handlers/settings.py` — MVP hub text (Profile + Notifications status), settings:risk → mvp_risk_kb
- `projects/polymarket/crusaderbot/bot/handlers/presets.py` — MVP auto trade display (Conservative/Balanced/Aggressive), mvp_auto_trade_kb, updated _MENU_BUTTONS_CUSTOMIZE, MVP preset confirmation labels
- `projects/polymarket/crusaderbot/bot/handlers/positions.py` — MVP portfolio text (Balance/Performance/Positions only)

**Created:**
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-mvp-reset-v1.md` (this file)

---

## 4. What Is Working

- `/start` new user → clean welcome bubble → single "🚀 Get Started" CTA → dashboard
- `/start` returning user → dashboard directly (ALLOWLISTED) or waitlist
- Welcome text: no internal telemetry, no "scanning", "preset", "signal following" text
- Main reply keyboard: 5 buttons, all functional
- Dashboard: Bot status / Account / Today PnL — no dead buttons, no complex cta logic
- Auto Trade: Conservative/Balanced/Aggressive mapped to real preset keys, confirmation card uses MVP labels
- Portfolio: Balance/Performance/Positions text, Positions button → show_positions, Refresh → show_portfolio
- Settings: Notifications stub + Risk Profile screen working
- Risk Profile: MVP 3-option screen with current risk highlighted, set_risk:* callbacks active
- Old menu surfaces archived (not reachable from main user flow, callbacks retained for in-flight safety)
- python3 -m compileall: CLEAN
- python3 -m py_compile (all touched files): CLEAN

---

## 5. Known Issues

- `_on_customize` and `_on_edit` in presets.py still reference "Phase 5G" in user-facing text — minor cosmetic follow-up
- wizard_menu_tap regex in presets.py includes 📊 (Insights) which is no longer a main menu button — harmless, no user impact
- `_legacy_dashboard_kb`, `_legacy_portfolio_kb`, `_legacy_get_started_kb`, `_legacy_settings_hub_kb` archived in place — can be removed in a future cleanup lane
- portfolio_callback in positions.py still handles `portfolio:chart`, `portfolio:insights`, `portfolio:trades` — unreachable from MVP keyboard but retained for in-flight safety

---

## 6. What Is Next

WARP🔹CMD review of this PR (STANDARD tier, NARROW INTEGRATION).

After merge, candidate follow-up lanes:
- Wipe remaining legacy _legacy_* functions in a MINOR cleanup lane
- Wire `notify_order_filled()` into paper executor (WARP/notifications-paper-wire — already in NEXT PRIORITY)

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: Telegram MVP UX reset — keyboard surfaces, menu routing, onboarding flow, screen text
Not in Scope: Copy Wallet, Signal Feeds, Insights, Premium, execution logic, trading engine, DB schema, risk backend, live trading guard
Suggested Next: WARP🔹CMD review
