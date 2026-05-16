# WARP•FORGE Report — telegram-ux-v5-overhaul

**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** V5 Dashboard rendering, main menu layout, Auto Mode routing
**Not in Scope:** Trading execution engine, live-mode guards, referral surface (deferred)
**Suggested Next Step:** WARP🔹CMD review → deploy to Fly.io

---

## 1. What Was Built

V5 "AUTOBOT" UI overhaul for the CrusaderBot Telegram bot:

- **Branding** — All primary headers updated to `🏛️ 𝗖𝗥𝗨𝗦𝗔𝗗𝗘𝗥 | 𝗔𝗨𝗧𝗢𝗕𝗢𝗧` across dashboard, onboarding, preset picker, status card, and wizard steps.
- **Dynamic Pulse Line** — Dashboard now shows last trade action (`📈 Last: Bought — <market>` / `📉 Last: Closed — <market>`) or falls back to `📡 Scanning Polymarket liquidity...` when no positions exist. Silent on DB error.
- **Monospaced Financial Figures** — Balance, Exposure, Equity, and all P&L values wrapped in `<code>` tags for mobile-aligned monospaced rendering.
- **Fixed 5-Button Main Menu** — Replaced state-driven 3-state keyboard with a fixed 2-column grid: `[📊 Dashboard | 💼 Portfolio] / [🤖 Auto Mode | ⚙️ Settings] / [❓ Help]`. Backward-compat aliases kept for old labels.
- **Dashboard Inline Keyboard** — `p5_dashboard_kb()` rebuilt as 2-column 4-button layout: `[Auto Mode | Portfolio] / [Settings | Wallet]`.
- **Menu Routing Sync** — `MAIN_MENU_ROUTES` updated with V5 labels + compat aliases. `menu:portfolio` callback wired in dispatcher.
- **Test Suite Updated** — `test_phase5d_grid_menu_split.py` updated to assert V5 fixed-grid layout and new route set.

---

## 2. Current System Architecture

```
Telegram Update
    ↓
dispatcher.py (group=-1: menu:*, nav:*, emergency)
    ↓
_text_router → MAIN_MENU_ROUTES (menus/main.py)
    │
    ├─ 📊 Dashboard    → handlers/dashboard.py::dashboard()
    ├─ 💼 Portfolio    → handlers/positions.py::show_portfolio()
    ├─ 🤖 Auto Mode   → handlers/presets.py::show_preset_picker()
    ├─ ⚙️ Settings    → handlers/settings.py::settings_hub_root()
    └─ ❓ Help        → handlers/onboarding.py::help_handler()

dashboard.py::_build_dashboard_message()
    ├─ _fetch_stats()            ← DB: positions + ledger
    ├─ _fetch_last_trade_action() ← DB: positions + markets (NEW)
    └─ messages.dashboard_text(pulse_line=...) (UPDATED)
```

---

## 3. Files Created / Modified

| Action | Path |
|--------|------|
| Modified | `projects/polymarket/crusaderbot/bot/messages.py` |
| Modified | `projects/polymarket/crusaderbot/bot/handlers/dashboard.py` |
| Modified | `projects/polymarket/crusaderbot/bot/keyboards/__init__.py` |
| Modified | `projects/polymarket/crusaderbot/bot/menus/main.py` |
| Modified | `projects/polymarket/crusaderbot/bot/handlers/onboarding.py` |
| Modified | `projects/polymarket/crusaderbot/bot/handlers/presets.py` |
| Modified | `projects/polymarket/crusaderbot/bot/dispatcher.py` |
| Modified | `projects/polymarket/crusaderbot/tests/test_phase5d_grid_menu_split.py` |
| Created  | `projects/polymarket/crusaderbot/reports/forge/telegram-ux-v5-overhaul.md` |

---

## 4. What Is Working

- `dashboard_text()` — `pulse_line` param with default fallback; `<code>`-wrapped: Balance, Exposure, Equity, PnL Today, 7d, 30d, All-Time, Volume.
- `_fetch_last_trade_action()` — queries latest position action; silent exception handling (never crashes dashboard render).
- `main_menu()` — fixed 5-button 2-column grid; backward-compat `strategy_key`/`auto_on` params kept but unused.
- `p5_dashboard_kb()` — 2-column 4-button inline: `[Auto Mode | Portfolio] / [Settings | Wallet]`.
- `MAIN_MENU_ROUTES` — V5 routes + 3 backward-compat aliases for cached keyboards from previous deploys.
- `menu:portfolio` — wired in `_menu_nav_cb`, routes to `show_portfolio`.
- All modified files pass AST syntax check.
- Webtrader backend (`/api/web/*`) unaffected — separate router, no shared code with bot UI layer.

---

## 5. Known Issues

- Referrals button deferred per WARP🔹CMD instruction — `🔗 Referrals` not in this release.
- `crusaderbot-logo.png` binary missing (pre-existing WebTrader deploy blocker, out of scope).
- Test runner unavailable in sandbox (missing native cryptography libs) — AST syntax validation only.

---

## 6. What Is Next

- WARP🔹CMD review → merge → Fly.io deploy.
- Referrals surface (`🔗 Referrals` button + `menu:referrals` routing) — next lane.
- Consider adding `🚨 Emergency` as a 6th button when Referrals lands, completing the full 6-button spec.
