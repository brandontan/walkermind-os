# WARP•FORGE REPORT — ux-overhaul

**Validation Tier:** STANDARD
**Claim Level:** PRESENTATION
**Validation Target:** Telegram UX — all 9 parts of the premium-grade overhaul
**Not in Scope:** Trading logic, DB schema changes, signal scan logic, new commands, Copy Trade API integration
**Suggested Next Step:** WARP🔹CMD review → merge (no SENTINEL required)

---

## 1. What was built

Full Telegram UX redesign across 9 parts:

**Part 1 — Main Menu**: New 6-button layout. "⚙️ Settings" replaces "💰 Wallet" (Wallet now inside Settings hub). "🛑 Stop Bot" replaces "🚨 Emergency". Copy Trade promoted to row 2.

**Part 2 — TP/SL**: Replaced manual `"25 25"` text input with 2-step preset button flow. Step 1: Take Profit (+5/10/15/25/Custom). Step 2: Stop Loss (-5/8/10/15/Custom). Validation: TP 1–100, SL 1–50.

**Part 3 — Capital Allocation**: Replaced manual text input with preset buttons showing real dollar amounts calculated from user balance (10%/25%/50%/75%/Custom). 95% hard cap enforced.

**Part 4 — Strategy Selection**: Replaced checkbox list with descriptive card UI. User-facing names: Signal, Edge Finder, Momentum Reversal, All Strategies. Internal mapping preserved: edge_finder→value, momentum_reversal→momentum_reversal. No "R6b+" or internal names exposed.

**Part 5 — Copy Trade API fallback**: Wrapped `fetch_top_wallets` in try/except. Shows graceful fallback with [🔄 Retry] [↩️ Back] on API failure.

**Part 6 — Insights fix**: Changed empty-state threshold from 0 to 3 closed trades. Shows "Not enough data yet. Need at least 3 closed trades. Current: N closed trades." Removed [Dashboard] button from insights keyboard.

**Part 7 — Settings Hub**: New ⚙️ Settings surface replacing old auto-redeem-only handler. Hub: Wallet, TP/SL, Capital Allocation, Risk Profile, Notifications, Mode (Paper/Live), Back.

**Part 8 — Auto-Trade dedup fix**: `setup_root` now renders a single clean strategy card message (no conditional preset status/picker dual-path). Eliminated the "dual-render" pattern.

**Part 9 — My Trades formatting**: Upgraded position cards to show `{side} @ ${entry} → ${current} ({pnl_pct}%)` + `TP: +N% | SL: -N%`. Removed redundant [Dashboard] button from main KB and close_success_kb.

---

## 2. Current system architecture

```
Reply keyboard (main_menu)
  ├─ 📊 Dashboard   → dashboard.dashboard
  ├─ 📈 My Trades   → my_trades.my_trades (upgraded cards + TP/SL)
  ├─ 🤖 Auto-Trade  → setup.setup_root (strategy card — single render)
  ├─ 🐋 Copy Trade  → copy_trade.menu_copytrade_handler (graceful fallback)
  ├─ ⚙️ Settings    → settings.settings_hub_root (new hub)
  └─ 🛑 Stop Bot    → emergency.emergency_root

Settings hub (settings:* callbacks)
  ├─ settings:wallet     → wallet surface inline
  ├─ settings:tpsl       → tp_set:* flow (2 steps)
  ├─ settings:capital    → cap_set:* flow (preset buttons)
  ├─ settings:risk       → risk_picker
  ├─ settings:notifications → stub
  ├─ settings:mode       → mode_picker
  └─ settings:back / hub → re-render

Strategy card (strategy:* callbacks)
  ├─ strategy:signal           → update_settings(["signal"])
  ├─ strategy:edge_finder      → update_settings(["value"])
  ├─ strategy:momentum_reversal → update_settings(["momentum_reversal"])
  ├─ strategy:all              → update_settings(["signal","value","momentum_reversal"])
  └─ strategy:back             → main_menu reply keyboard

Text input flow priority (dispatcher._text_router)
  1. Main menu button check (clears awaiting)
  2. live_gate.text_input
  3. activation.text_input
  4. copy_trade.text_input
  5. settings_text_input  ← NEW (handles tpsl_tp / tpsl_sl)
  6. setup.text_input     (handles capital_pct)
```

---

## 3. Files created / modified

**Modified:**
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py` — main_menu() new layout; strategy_card_kb() added; insights_kb() dashboard button removed
- `projects/polymarket/crusaderbot/bot/keyboards/settings.py` — complete rewrite: settings_hub_kb, tp_preset_kb, sl_preset_kb, tpsl_confirm_kb, capital_preset_kb
- `projects/polymarket/crusaderbot/bot/keyboards/my_trades.py` — removed Dashboard button from my_trades_main_kb and close_success_kb
- `projects/polymarket/crusaderbot/bot/menus/main.py` — updated routes: Settings, Stop Bot; removed Wallet, Emergency
- `projects/polymarket/crusaderbot/bot/handlers/settings.py` — complete overwrite: settings_hub_root, tp_set_callback, sl_set_callback, cap_set_callback, settings_text_input
- `projects/polymarket/crusaderbot/bot/handlers/setup.py` — setup_root now shows strategy cards; set_strategy_card added; setup_callback sub=="strategy" routes to card UI
- `projects/polymarket/crusaderbot/bot/handlers/my_trades.py` — _format_positions_section upgraded with TP/SL display; _build_main_text passes tp_pct/sl_pct; my_trades + back_cb fetch settings
- `projects/polymarket/crusaderbot/bot/handlers/pnl_insights.py` — format_insights empty state threshold raised to 3; message format updated
- `projects/polymarket/crusaderbot/bot/handlers/copy_trade.py` — discover action wrapped in try/except; graceful fallback message with Retry/Back buttons
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — wired: strategy:, tp_set:, sl_set:, cap_set:, settings_text_input; imports added
- `projects/polymarket/crusaderbot/tests/test_pnl_insights.py` — updated 2 tests for new insights_kb and format_insights empty state

**Created:**
- `projects/polymarket/crusaderbot/tests/test_ux_overhaul.py` — 45 hermetic tests
- `projects/polymarket/crusaderbot/reports/forge/ux-overhaul.md` — this report

---

## 4. What is working

- Main menu: new 6-button layout with Settings hub and Stop Bot
- TP/SL: 2-step preset flow with validation (TP 1–100, SL 1–50); Custom path sets awaiting and prompts
- Capital allocation: preset buttons with live balance-derived dollar amounts; Custom path reuses existing setup.text_input
- Strategy cards: descriptive UX, backend mapping correct (edge_finder→value)
- Settings hub: Wallet, TP/SL, Capital, Risk, Notifications stub, Mode — all wired
- Copy Trade discover: try/except wraps fetch_top_wallets; graceful Retry/Back fallback
- Insights: threshold = 3, shows current count, no Dashboard button
- Auto-Trade: single render path, no duplicate menu group
- My Trades: TP/SL shown per position; Dashboard button removed from KB and close_success_kb
- Dispatcher: all new callbacks registered, settings_text_input in priority chain
- 45 hermetic tests in test_ux_overhaul.py; 2 existing tests in test_pnl_insights.py updated

---

## 5. Known issues

- Notifications settings stub (settings:notifications) shows placeholder; full notification preferences not in scope.
- TP/SL flow: if user types Custom for TP then taps a menu button before completing SL, pending_tp is lost (edge case, low risk).
- insights:full_report callback is wired in insights_kb but the handler only has insights:refresh logic in insights_cb; full_report routes to same refresh action via pattern `^insights:` catch-all.
- Strategy card Back button sends a new reply keyboard message (adds to chat), not edit — by design since InlineKeyboardMarkup cannot switch to ReplyKeyboardMarkup in place.

---

## 6. What is next

WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/ux-overhaul.md
Tier: STANDARD
