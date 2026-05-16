# WARP•FORGE REPORT — phase5-fix-r1

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: 3 UX bugs: <pre> COPY CODE buttons on dashboard, missing persistent ReplyKeyboard main menu, My Trades callback not responding
Not in Scope: DB schema changes, live-trading guards, strategy logic, non-dashboard <pre> tags (wallet address blocks are intentional monospace)
Suggested Next Step: WARP🔹CMD review required. Report: projects/polymarket/crusaderbot/reports/forge/phase5-fix-r1.md. Tier: STANDARD

---

## 1. What Was Built

Three targeted UX fixes on top of the Phase 5 Full UX Rebuild:

**Fix 1 — Remove `<pre>` from dashboard and autotrade screens**
- `dashboard_text()` in `messages.py`: removed 4 `<pre>`/`</pre>` blocks wrapping Portfolio, P&L, Trading Stats, and Auto-Trade sections. Plain HTML text now, no COPY CODE button.
- `preset_confirm_text()`: removed 1 `<pre>` block.
- `preset_active_text()`: removed 2 `<pre>` blocks.
- `trades_text()` position rows: removed `<pre>` wrapping per-position hierarchy lines.
- `history_cb()` in `handlers/trades.py`: removed `<pre>` from history row format string.

**Fix 2 — Persistent 5-button ReplyKeyboard**
- Added `main_menu_keyboard()` to `bot/keyboards/__init__.py`: fixed layout (📊 Dashboard / 🤖 Auto-Trade / 💰 Wallet / 📈 My Trades / 🚨 Emergency), `resize_keyboard=True`, `is_persistent=True`.
- `show_dashboard()` in `handlers/dashboard.py`: now sends dashboard message with `reply_markup=main_menu_keyboard()` instead of `p5_dashboard_kb`. Persistent keyboard attached on every fresh dashboard render.
- `show_dashboard_for_cb()`: callback-edit path keeps inline keyboard (edit_message_text requires InlineKeyboard); reply fallback uses `main_menu_keyboard()`.
- `dispatcher.py`: 4 group=-1 `MessageHandler` entries for button texts `📊 Dashboard`, `🤖 Auto-Trade`, `💰 Wallet`, `📈 My Trades` — fire before any `ConversationHandler` state, no double-routing risk since they are NOT added to `MAIN_MENU_ROUTES`. `🚨 Emergency` already in `MAIN_MENU_ROUTES` and handled by `_text_router`; no group=-1 duplicate needed.

**Fix 3 — My Trades callback robustness**
- `show_trades()` in `handlers/trades.py`: wrapped `_fetch_trades()` call in `try/except`. On DB error: logs at ERROR, falls through to empty-state render instead of silently dropping the callback.
- `📈 My Trades` text button registered at group=-1 in dispatcher — works from within ConversationHandler states.

---

## 2. Current System Architecture

```
Telegram Update
    │
    ├── group=-1  CallbackQueryHandler(^menu:)   → _menu_nav_cb  → screen handlers
    ├── group=-1  MessageHandler(📊 Dashboard)   → dashboard()
    ├── group=-1  MessageHandler(🤖 Auto-Trade)  → show_autotrade()
    ├── group=-1  MessageHandler(💰 Wallet)      → wallet_root()
    ├── group=-1  MessageHandler(📈 My Trades)   → show_trades()
    │
    ├── group=0   ConversationHandlers (start, copy_trade, customize, presets)
    ├── group=0   CommandHandlers
    ├── group=0   CallbackQueryHandlers (p5, legacy, settings, etc.)
    └── group=0   MessageHandler(TEXT) → _text_router → MAIN_MENU_ROUTES + wizard fallbacks

Dashboard message:
    show_dashboard()        → reply_markup=main_menu_keyboard() (ReplyKeyboard)
    show_dashboard_for_cb() → edit: reply_markup=p5_dashboard_kb (InlineKeyboard)
                              reply fallback: main_menu_keyboard()
```

---

## 3. Files Created / Modified

Modified:
- `projects/polymarket/crusaderbot/bot/messages.py`
- `projects/polymarket/crusaderbot/bot/handlers/trades.py`
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py`
- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py`
- `projects/polymarket/crusaderbot/bot/dispatcher.py`
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

Created:
- `projects/polymarket/crusaderbot/reports/forge/phase5-fix-r1.md`

---

## 4. What Is Working

- Dashboard, preset confirm, preset active, trades, history screens: zero `<pre>` blocks → no COPY CODE button anywhere in these flows.
- `main_menu_keyboard()` function available in `bot/keyboards/__init__.py`.
- Every fresh dashboard render (command, text button, start flow) attaches persistent 5-button ReplyKeyboard.
- `📊 Dashboard`, `🤖 Auto-Trade`, `💰 Wallet`, `📈 My Trades` persistent buttons: registered at group=-1, work from within any ConversationHandler state.
- `show_trades()`: DB errors no longer produce silent failures; falls through to empty-state render.
- `test_ux_overhaul.py` 45 tests green. `test_phase5i_my_trades.py` 13 tests green. 119 tests total across 4 relevant test files — all pass.
- ruff: all checks passed.
- compileall: all 5 changed .py files compile clean.

---

## 5. Known Issues

- `show_dashboard_for_cb()` in callback-edit path still sends `p5_dashboard_kb` (InlineKeyboard). Cannot attach ReplyKeyboard via `edit_message_text`. On first fresh render the ReplyKeyboard is attached; `is_persistent=True` keeps it visible for subsequent edits.
- Pre-existing test failures in `test_trade_notifications.py` and `test_ui_premium_pack_1.py` (async tests missing `pytest-asyncio` plugin in test env) are unrelated to this fix set.
- `🚨 Emergency` persistent button is NOT registered at group=-1; it routes via `_text_router` → `MAIN_MENU_ROUTES`. Will not override ConversationHandler text states. Acceptable: Emergency is also accessible via InlineKeyboard `p5:emergency:ask:*` callbacks which are at group=0.

---

## 6. What Is Next

- Deploy updated code to Fly.io (PAPER ONLY — activation guards OFF).
- Apply migration 027 and migration 028 before Fly.io deploy.
- Verify on live bot: no COPY CODE on dashboard, persistent keyboard visible, My Trades responds.
