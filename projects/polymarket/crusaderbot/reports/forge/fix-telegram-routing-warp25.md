# WARP•FORGE Report — fix-telegram-routing-warp25

**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** bot/dispatcher.py, bot/keyboards/__init__.py
**Not in Scope:** WebTrader, scheduler, DB schema, signal pipeline

---

## 1. What Was Built

Four routing defects diagnosed and resolved:

1. **`menu:positions` routing** — `_menu_nav_cb` had no case for `menu:positions`. Added explicit routing to `positions.show_positions` (answers internally on callback path, matching the `menu:portfolio` pattern).

2. **Dead `close_position_cb` import removed** — `close_position_cb` was imported from `handlers/dashboard.py` in `dispatcher.py` but never registered as a `CallbackQueryHandler`. The correct registration (`close_ask_cb` from `trades.py` for pattern `^close_position:(?!confirm:)`) was already present. Dead import removed; single handler confirmed.

3. **`preset_picker()` in `keyboards/__init__.py` rewritten** — The function had 8 hardcoded stale preset keys (trend_breakout, contrarian, close_sweep, pair_arb, ensemble) that do not exist in `domain/preset/presets.py`. Any tap on those ghost buttons would silently fail the autotrade handler lookup. Replaced with a dynamic builder using `list_presets()` from the domain layer. Labels: `{emoji} {name}` — all ≤ 20 chars for current 5 presets. Recommended preset gets ⭐ badge.

4. **`Back` from Positions → Portfolio verified** — `positions_list_kb()` uses `home_back_row("portfolio:portfolio")`. `home_back_row` emits a Back button with `callback_data="portfolio:portfolio"`. This matches the `^portfolio:` pattern registered in `dispatcher.py` which routes to `portfolio_callback` → `show_portfolio`. No change needed; confirmed working.

---

## 2. Current System Architecture

```
Telegram user tap
  │
  ├─ group=-1 MessageHandler (💼 Trades (N)) → positions.show_positions
  ├─ group=-1 CallbackQueryHandler (^menu:)  → _menu_nav_cb
  │     ├─ menu:portfolio  → show_portfolio   [answers internally]
  │     ├─ menu:positions  → show_positions   [answers internally] ← NEW
  │     ├─ menu:trades     → show_trades
  │     └─ menu:dashboard/autotrade/wallet/emergency/settings
  │
  ├─ CallbackQueryHandler (^close_position:(?!confirm:)) → close_ask_cb [trades.py]
  ├─ CallbackQueryHandler (^close_position:confirm:)     → close_confirm_cb [trades.py]
  │
  ├─ CallbackQueryHandler (^portfolio:) → portfolio_callback
  │     └─ portfolio:positions → show_positions
  │     └─ portfolio:portfolio → show_portfolio [Back from positions]
  │
  └─ CallbackQueryHandler (^p5:(preset|confirm|active):|^auto_trade:) → autotrade_callback
        └─ p5:preset:{key} → looks up domain preset by key [now uses correct keys]
```

---

## 3. Files Modified

- `projects/polymarket/crusaderbot/bot/dispatcher.py` — removed dead `close_position_cb` import; added `menu:positions` case in `_menu_nav_cb`
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py` — rewrote `preset_picker()` to use `list_presets()` from domain layer with validated short labels

---

## 4. What Is Working

- `menu:positions` callback now routes to `show_positions` from any surface
- `close_position:{id}` has a single registered handler (`close_ask_cb` from `trades.py`); no duplicate registration; dead import gone
- Preset picker renders only the 5 domain-registered presets (whale_mirror, signal_sniper, hybrid, value_hunter, full_auto) with labels ≤ 20 chars
- Back from Positions → Portfolio confirmed via `portfolio:portfolio` → `portfolio_callback` → `show_portfolio`
- `compileall` clean on all modified files

---

## 5. Known Issues

- None introduced by this task

---

## 6. What Is Next

- WARP🔹CMD review and merge decision
- No migration required; no Fly.io redeploy dependency (routing-only fix)

---

**Suggested Next Step:** WARP🔹CMD review required. Tier: STANDARD — no SENTINEL run needed.
