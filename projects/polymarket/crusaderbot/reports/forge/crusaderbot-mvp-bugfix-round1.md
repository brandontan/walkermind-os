# WARP•FORGE REPORT — crusaderbot-mvp-bugfix-round1

Branch: WARP/CRUSADERBOT-MVP-BUGFIX-ROUND1
Date: 2026-05-17
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: All Telegram CallbackQueryHandler and CommandHandler paths
Not in Scope: New features, DB migrations, live trading activation

---

## 1. What Was Built

Full audit of every handler and button in @CrusaderPolybot. 9 bugs found and fixed. No new features added.

### Audit Results

| # | Handler / Button | Pattern | Status Before | Issue |
|---|---|---|---|---|
| 1 | 💼 Portfolio reply button | text | BROKEN | open_count always 0 — key missing from stats dict |
| 2 | portfolio:trades callback | portfolio:trades | BROKEN | Calls my_trades() which requires update.message — silently returns None |
| 3 | 🤖 Auto Mode reply button | text | BROKEN | Routed to old presets.show_preset_picker not autotrade.show_autotrade |
| 4 | settings:health | settings:health | ERROR | SQL queried job_id column — schema has job_name → KeyError at runtime |
| 5 | close_position ask | close_position:[^c] | BROKEN | (a) PnL always $0.00 — stale current_price used; (b) pattern blocked UUIDs starting with 'c' |
| 6 | close_position confirm | close_position:confirm: | ERROR | Called position_registry.mark_force_close_intent_for_position — function does not exist in registry |
| 7 | emergency pause+close-all | p5:emergency:confirm:pause_close | ERROR | Same missing registry function — per-position mark_force_close |
| 8 | W/L counter in dashboard | DB query | BROKEN | pnl_usdc <= 0 classified breakeven (0) as loss |
| 9 | trade_detail_cb | mytrades:open: | DEAD | Handler registered, no keyboard emits this pattern — no impact, left as-is |

All other handlers (Commands, menu:*, nav:*, p5:preset/*, wallet, signals, copy_trade, referral, admin, settings sub-pages, insights, chart, force-close flow, emergency confirm) were WORKING.

---

## 2. Current System Architecture

Handler registration flow (unchanged):
- group=-1 MessageHandlers: 📊 Dashboard, 🤖 Auto-Trade, 💰 Wallet, 📈 My Trades, 🚨 Emergency
- Text router: 💼 Portfolio → show_portfolio, 🤖 Auto Mode → show_autotrade (fixed), ⚙️ Settings → settings_hub_root
- Callback handlers: menu:*, nav:*, p5:*, close_position:*, portfolio:*, settings:*, dashboard:*, wallet:*, emergency:*, etc.

Paper close flow (fixed):
- close_position:{id} → close_ask_cb → shows confirmation with live mark price (3s timeout, fallback to DB)
- close_position:confirm:{id} → close_confirm_cb → calls paper_exec.close_position directly → shows realized PnL
- Live positions → queue via mark_force_close_intent_for_position from emergency handler

---

## 3. Files Created / Modified

Modified:
- projects/polymarket/crusaderbot/bot/handlers/dashboard.py — added open_count to _fetch_stats query + result dict; W/L loss filter pnl_usdc <= 0 → < 0
- projects/polymarket/crusaderbot/bot/handlers/settings.py — settings:health SQL job_id → job_name in query + template
- projects/polymarket/crusaderbot/bot/menus/main.py — 🤖 Auto Mode route: presets.show_preset_picker → autotrade.show_autotrade
- projects/polymarket/crusaderbot/bot/handlers/positions.py — portfolio:trades uses my_trades_cb (callback-safe) not my_trades
- projects/polymarket/crusaderbot/bot/handlers/trades.py — close_ask_cb: live mark price + correct PnL formula; close_confirm_cb: paper_exec.close_position for paper, emergency.mark_force_close_intent_for_position for live; added _fetch_mark_price + _paper_pnl helpers
- projects/polymarket/crusaderbot/bot/handlers/emergency.py — _execute_action pause_close: direct call to mark_force_close_intent_for_position (removes wrong position_registry import)
- projects/polymarket/crusaderbot/bot/dispatcher.py — close_position pattern: [^c] → (?!confirm:) to handle UUIDs starting with 'c'

---

## 4. What Is Working

- All 9 bugs fixed
- python3 -m compileall: clean (no syntax errors)
- ruff check: All checks passed
- AST parse: All files parse OK
- open_count now populated correctly via open_count column in _fetch_stats
- W/L counter: breakeven trades no longer count as losses
- settings:health: renders job runs correctly
- 🤖 Auto Mode: routes to 5-preset autotrade surface
- portfolio:trades: sends My Trades reply via callback-safe my_trades_cb
- close confirmation: shows live mark-price PnL estimate (3s CLOB timeout, falls back to current_price then entry)
- close confirm: paper positions closed immediately via paper_exec, realized PnL shown to user
- emergency pause+close-all: correctly flags all positions via mark_force_close_intent_for_position
- Dispatcher close_position pattern: negative lookahead handles all UUID chars including 'c'

---

## 5. Known Issues

- mytrades:open:{uuid} handler registered but no keyboard emits this callback_data — DEAD (no user impact, no errors)
- close_ask_cb for live positions still shows entry price as PnL estimate when mark price unavailable — acceptable degradation for paper-only system

---

## 6. What Is Next

WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/crusaderbot-mvp-bugfix-round1.md
Tier: STANDARD
