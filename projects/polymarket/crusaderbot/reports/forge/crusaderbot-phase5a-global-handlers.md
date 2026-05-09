# WARP•FORGE Report — CrusaderBot Phase 5A Global Handlers

Branch: `claude/fix-menu-handlers-Y8tp9`
Declared branch: `WARP/CRUSADERBOT-PHASE5A-GLOBAL-HANDLERS`
Note: session harness pre-set `claude/fix-menu-handlers-Y8tp9`; work proceeded on that branch per system-level authority. CLAUDE.md branch naming rule violation noted for WARP🔹CMD awareness.

Validation Tier: MINOR
Claim Level: NARROW INTEGRATION — handler routing fix + menu layout change. No business logic, trading, execution, or risk gate touched.
Validation Target: `_text_router` priority order; `main_menu()` keyboard layout; `MAIN_MENU_ROUTES`; `my_trades` combined view; `/settings` command registration
Not in Scope: trading logic, execution, risk gate, strategy config internals, database schema, activation guards, Dashboard content (5B), preset system (5C)
Suggested Next Step: WARP🔹CMD review — merge direct (MINOR, no SENTINEL required)

---

## 1. What was built

Two changes shipped in one PR:

**Global handler priority fix** — `_text_router` in `bot/dispatcher.py` now checks main menu button text BEFORE delegating to `activation.text_input` or `setup.text_input`. If the incoming text matches a registered menu route, any pending `ctx.user_data['awaiting']` key is cleared and the menu handler fires immediately. This eliminates "Couldn't parse that — try again or send /menu to exit" errors that appeared when users tapped a menu button mid-setup-flow (e.g., while the bot was awaiting a capital-% or TP/SL input).

**5-button main menu** — Main menu reduced from 8 to 5 buttons:

```
[📊 Dashboard]  [🤖 Auto-Trade]
[💰 Wallet]     [📈 My Trades]
[🚨 Emergency]
```

- `🤖 Setup` renamed to `🤖 Auto-Trade` (same handler: `setup.setup_root`)
- `📈 Positions` + `📋 Activity` merged into `📈 My Trades` (new handler: `positions.my_trades`)
- `🛑 Emergency` emoji changed to `🚨 Emergency` (same handler: `emergency.emergency_root`)
- `⚙️ Settings` removed from button menu → `/settings` command registered
- `ℹ️ Help` removed from button menu → `/help` already registered

`/settings` `CommandHandler` added to `dispatcher.register()` so the command is reachable even without the button.

`📈 My Trades` handler is a fast combined view: up to 10 open positions (no mark-price fetch) + last 5 orders. Full live-P&L + force-close remains reachable via `/positions`.

---

## 2. Current system architecture

```
Telegram client
  │
  ▼
bot.dispatcher._text_router  [CHANGED — menu routes checked first]
  │
  ├── get_menu_route(text) → match?
  │     └── YES: clear ctx.user_data['awaiting'] → route to handler → return
  │     └── NO: fall through
  │
  ├── activation.text_input(update, ctx)
  ├── setup.text_input(update, ctx)
  └── (no further handling if both return False)

bot.menus.main.MAIN_MENU_ROUTES  [CHANGED — 8 → 5 entries]
  📊 Dashboard  → bot.handlers.dashboard.dashboard
  🤖 Auto-Trade → bot.handlers.setup.setup_root
  💰 Wallet     → bot.handlers.wallet.wallet_root
  📈 My Trades  → bot.handlers.positions.my_trades    [NEW]
  🚨 Emergency  → bot.handlers.emergency.emergency_root

bot.keyboards.main_menu()  [CHANGED — 3 rows, 5 buttons]
  row 0: [📊 Dashboard] [🤖 Auto-Trade]
  row 1: [💰 Wallet]    [📈 My Trades]
  row 2: [🚨 Emergency]

bot.dispatcher.register()  [CHANGED — added /settings]
  CommandHandler("settings") → settings_handler.settings_root
```

---

## 3. Files created / modified

Modified:

* `projects/polymarket/crusaderbot/bot/dispatcher.py` — `_text_router` restructured: menu-route check moves before activation/setup text handlers; clears `awaiting` on menu match. `CommandHandler("settings", settings_handler.settings_root)` added.
* `projects/polymarket/crusaderbot/bot/keyboards/__init__.py` — `main_menu()` changed from 4-row/8-button to 3-row/5-button layout with updated labels and emoji.
* `projects/polymarket/crusaderbot/bot/menus/main.py` — `MAIN_MENU_ROUTES` reduced from 8 entries to 5; `onboarding` and `settings_handler` imports removed (no longer needed); docstring updated.
* `projects/polymarket/crusaderbot/bot/handlers/positions.py` — `my_trades()` handler added (combined open-positions summary + recent-activity view, no mark-price fetch).
* `projects/polymarket/crusaderbot/bot/handlers/onboarding.py` — `help_handler` updated: new "📱 Main Menu" section documents all 5 buttons; `/settings` added to Account commands; `/positions` description clarified.

---

## 4. What is working

* `_text_router` menu-route check precedes all awaiting-state handlers — verified by `inspect.getsource` index comparison in local check.
* `MAIN_MENU_ROUTES` contains exactly the 5 expected keys — verified by set equality assertion against `{'📊 Dashboard','🤖 Auto-Trade','💰 Wallet','📈 My Trades','🚨 Emergency'}`.
* `my_trades` is importable and registered as the `📈 My Trades` route.
* `CommandHandler("settings")` registered in `dispatcher.register()` — `settings_handler.settings_root` is reachable via `/settings`.
* AST parse clean on all 5 modified files — no syntax errors.
* 784/784 tests pass (pre-existing suite, `test_api_ops.py` excluded due to missing `eth_account` in test env — unrelated to this lane). All 20 `test_positions_handler.py` tests pass. `test_smoke.py` and `test_health.py` unchanged green.
* No activation guard state changed. No trading/execution/risk path touched.

Done criteria check:
- [x] Tap Dashboard mid-Setup → menu-route matched before setup.text_input, `awaiting` cleared, Dashboard renders
- [x] Tap Emergency mid-Setup → same priority fix applies; `🚨 Emergency` registered in MAIN_MENU_ROUTES
- [x] Tap Auto-Trade from Dashboard → `🤖 Auto-Trade` → `setup.setup_root` → Setup renders
- [x] All existing ConversationHandler flows (activation CONFIRM, capital_pct, tpsl, copy_target) still work: menu-route check returns False for non-button text, activation/setup text_input consumers run as before
- [x] `/settings` responds — registered in dispatcher
- [x] `/help` responds — unchanged
- [x] 784 tests green
- [x] No activation guard state changed

---

## 5. Known issues

* Branch name is `claude/fix-menu-handlers-Y8tp9` (harness-generated) rather than `WARP/CRUSADERBOT-PHASE5A-GLOBAL-HANDLERS`. CLAUDE.md branch naming rule is violated; flagged for WARP🔹CMD awareness. No functional impact.
* `my_trades` shows open positions without mark prices (fast, no CLOB call). Users who want live P&L and the force-close button must use `/positions`. This is intentional and noted in the handler's inline hint.
* `dashboard.positions` and `dashboard.close_position_cb` are still defined (legacy, pre-R12d). Not deleted in this lane — cleanup deferred per prior r12d report note.
* Old button labels (`🤖 Setup`, `📈 Positions`, `📋 Activity`, `🛑 Emergency`, `⚙️ Settings`, `ℹ️ Help`) no longer appear in the main keyboard. Any hardcoded test or external reference to those exact strings would stop matching — none found in the test suite.

---

## 6. What is next

* WARP🔹CMD review + merge decision on this PR (MINOR).
* Phase 5B: Dashboard content enrichment (deferred from this lane per task scope).
* Phase 5C: Preset system (deferred).
* `dashboard.positions` / `dashboard.close_position_cb` cleanup can follow in a separate MINOR lane once WARP🔹CMD confirms no other surface depends on them.
