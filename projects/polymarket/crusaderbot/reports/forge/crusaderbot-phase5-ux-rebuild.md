# WARP•FORGE REPORT — crusaderbot-phase5-ux-rebuild

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: Telegram bot presentation layer — 6 screens, 5 handler files, keyboards, messages, dispatcher
Not in Scope: Trading logic, execution paths, DB schema (except migration 028), risk gates, activation guard constants
Suggested Next Step: WARP•SENTINEL validation required before merge (Tier MAJOR)

---

## 1. What Was Built

Full rebuild of CrusaderBot Telegram bot UI layer — 6 screens per visual design spec.
No changes to trading logic, execution paths, risk gates, or activation guard constants.

**Screen 01 — Welcome / Onboarding** (`start.py`)
- `/start` checks `users.onboarding_complete`: returning users go directly to Dashboard, new users enter 3-step onboarding flow
- Welcome card → Wallet init (seeds $1,000 paper balance) → Preset Picker → Deposit prompt → Dashboard
- `[Learn More]` → static FAQ → back to Welcome
- `ConversationHandler` with 3 states: `_WELCOME`, `_WALLET_READY`, `_DEPOSIT`

**Screen 02 — Dashboard** (`dashboard.py`)
- Full rewrite: `<pre>` monospace ledger blocks for all financial data
- 5 metric sections: Portfolio, P&L (today/7d/30d/all-time), Trading Stats, Auto-Trade status
- `p5_dashboard_kb()`: `[🤖 Edit Preset]` `[📈 My Trades]` `[💰 Wallet]` (or `[🤖 Get Started]` if no preset)
- `show_dashboard_for_cb()` retained for callback compat; `dashboard_nav_cb()` routes legacy `dashboard:*` callbacks

**Screen 03 — Auto-Trade Preset Picker** (`autotrade.py`)
- Routes to Picker if no active preset, or to Active Status if preset is running
- 5-button picker (one per row): Whale Mirror, Signal Sniper, Hybrid, Value Hunter, Full Auto + Back

**Screen 04 — Auto-Trade Confirmation / Active Status** (`autotrade.py`)
- Confirmation card: `<pre>` config block + `[✅ Activate]` `[✏️ Customize]` `[← Back]`
- Active status card: running metrics (since / trades today / P&L today) + `[✏️ Edit Config]` `[🔄 Switch Preset]` `[⏸ Pause]` `[🛑 Stop]`
- Activation writes preset config to `user_settings` (capital_alloc_pct, tp_pct, sl_pct, strategy_types, max_position_pct, preset_activated_at) and sets `auto_trade_on=True`

**Screen 04 Wizard — Customize** (`customize.py`)
- 5-step `ConversationHandler`: Capital → TP → SL → Copy Targets (copy_trade only) → Review
- Each step has preset button options + "Custom" text input path
- Save writes capital_alloc_pct / tp_pct / sl_pct to `user_settings`

**Screen 05+06 — My Trades** (`trades.py`)
- Open positions list (up to 10) with `<pre>` entry/size/current/P&L blocks
- Per-position `[🛑 Close]` button with confirmation dialog
- Close pattern: `close_position:{position_id}` → confirmation → `close_position:confirm:{id}`
- Close execution uses `mark_force_close_intent_for_position()` (force-close marker flow, no bypass)
- Recent Activity (last 5 closed trades) + `[📋 Full History]` view (last 20)
- Empty state with `[🤖 Set Up Auto-Trade]` CTA

**Wallet Screen** (`wallet.py`)
- Paper Mode badge, balance, short address, `[📋 Copy Address]` (shows full address as alert)

**Emergency Menu** (`emergency.py`)
- `menu:emergency` always routable via group=-1 nav
- 3 actions with per-action confirmation dialog: Pause / Pause+Close All / Lock Account
- Pause+Close All marks force-close intent on all open positions via position registry

**Supporting Modules**
- `bot/presets.py`: `PRESET_CONFIG` dict — 5 presets with full config (emoji, name, strategies, risk, capital_pct, tp_pct, sl_pct, max_pos_pct, has_copy_trade). Immutable reference; no trading logic.
- `bot/messages.py`: All message template builder functions. `<pre>` for financials, `html.escape()` on all external data. Pure functions, no DB calls.
- `bot/keyboards/__init__.py`: All original keyboards preserved + 25 new Phase 5 keyboards appended.

**Dispatcher Fix** (`dispatcher.py`)
- `menu:dashboard`, `menu:autotrade`, `menu:wallet`, `menu:trades`, `menu:emergency`, `menu:settings` all registered at `group=-1` before ConversationHandlers
- On match: routes directly to surface handler, clearing any pending wizard state
- All legacy callbacks (preset:, wallet:, dashboard:, emergency:, mytrades:, position:) preserved for backward compat with non-rewritten handlers

**Migration** (`migrations/028_add_preset_activated_at.sql`)
- Adds `preset_activated_at TIMESTAMPTZ` column to `user_settings` (idempotent `ADD COLUMN IF NOT EXISTS`)
- No tables dropped. No existing data modified.

---

## 2. Current System Architecture

```
Telegram User
     │
     ▼
bot/handlers/start.py         ←── /start (new + returning routing)
     │ onboarding_complete?
     ├── YES ──► dashboard.py
     └── NO  ──► 3-step onboarding ConversationHandler

5-button Main Menu (group=-1 in dispatcher):
  menu:dashboard  → dashboard.py show_dashboard_for_cb()
  menu:autotrade  → autotrade.py show_autotrade()
  menu:wallet     → wallet.py wallet_root_cb()
  menu:trades     → trades.py show_trades()
  menu:emergency  → emergency.py emergency_root_cb()

bot/presets.py          ←── PRESET_CONFIG (5 presets, immutable)
bot/messages.py         ←── message template builders (pure)
bot/keyboards/__init__  ←── all keyboard builders (legacy + Phase 5)
bot/handlers/autotrade.py ←── preset picker + confirm + active status
bot/handlers/customize.py ←── 5-step wizard ConversationHandler
bot/handlers/trades.py    ←── positions + activity + close flow
bot/handlers/emergency.py ←── emergency menu + confirmations

Unchanged pipeline: DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING
ENABLE_LIVE_TRADING guard: untouched. PAPER ONLY.
```

---

## 3. Files Created / Modified

Created:
- `projects/polymarket/crusaderbot/bot/presets.py`
- `projects/polymarket/crusaderbot/bot/messages.py`
- `projects/polymarket/crusaderbot/bot/handlers/start.py`
- `projects/polymarket/crusaderbot/bot/handlers/autotrade.py`
- `projects/polymarket/crusaderbot/bot/handlers/customize.py`
- `projects/polymarket/crusaderbot/bot/handlers/trades.py`
- `projects/polymarket/crusaderbot/migrations/028_add_preset_activated_at.sql`
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-phase5-ux-rebuild.md`

Modified (rewritten clean):
- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py`
- `projects/polymarket/crusaderbot/bot/handlers/wallet.py`
- `projects/polymarket/crusaderbot/bot/handlers/emergency.py`
- `projects/polymarket/crusaderbot/bot/dispatcher.py`
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py` (Phase 5 keyboards appended)

Unchanged (not in scope):
- All trading logic, execution, risk, strategy, DB schema files
- All non-rewritten handlers: settings.py, admin.py, copy_trade.py, positions.py, presets.py (legacy), onboarding.py (legacy), etc.

---

## 4. What Is Working

- `python3 -m compileall` — PASS (zero errors, all 11 new/modified files)
- `ruff check` — PASS (all checks passed)
- Activation guards: ENABLE_LIVE_TRADING, EXECUTION_PATH_VALIDATED, CAPITAL_MODE_CONFIRMED, RISK_CONTROLS_VALIDATED — all unchanged in config.py
- No DB tables dropped; migration 028 adds single nullable column (idempotent)
- All 5 preset configs defined in PRESET_CONFIG with correct values from spec
- Global handler fix: `menu:*` at group=-1 prevents ConversationHandler intercept of nav buttons
- `close_position:{id}` pattern correctly implemented (spec requirement 8)
- Paper Mode badge present in: dashboard, wallet, preset confirmation, preset active status
- `parse_mode=HTML` throughout (no Markdown)
- All financial numbers in `<pre>` monospace blocks
- `html.escape()` on all external variables in messages.py

---

## 5. Known Issues

- `preset_activated_at` column requires migration 028 to be applied before this code can be deployed to production. Column SELECT in `autotrade.py:_show_active_status()` will fail if migration is not run. Migration is idempotent.
- `customize.py` `build_customize_handler()` has empty `entry_points=[]` — wizard is entered programmatically via `start_customize_wizard()`. This means it cannot be triggered by a direct Telegram message; it requires being called from `autotrade.py`. This is intentional but means the wizard state is not persistent across bot restarts.
- Legacy `onboarding.py` and `presets.py` (handlers) remain active and are imported by dispatcher.py for backward compat. They are not in scope for this rebuild. Drift between old and new onboarding flows exists (both handle `/start`), but the new `build_start_handler()` ConversationHandler is registered first.
- `_PAPER_SEED` constant in start.py is `1000.0` — consistent with existing onboarding.py behavior.

---

## 6. What Is Next

- Apply migration 028 to production before deploying
- WARP•SENTINEL validation required (Tier MAJOR)
- After merge: deprecate legacy `onboarding.py` and `presets.py` handler flows (separate cleanup lane)
- WARP🔹CMD decision: remove legacy keyboard functions from keyboards/__init__.py (separate cleanup lane)
- Paper Mode badge in all 6 screens — verified present; live mode path deferred to activation gate lane
