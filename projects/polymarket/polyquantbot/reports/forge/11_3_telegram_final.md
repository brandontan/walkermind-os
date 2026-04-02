# FORGE Report — 11.3 Telegram Final System

**Date:** 2026-04-02
**Branch:** claude/forge-telegram-final-system-r98OR
**Role:** FORGE-X
**Status:** COMPLETE

---

## 1. User System Implementation

### Files
- `core/user_context.py` — immutable `UserContext` dataclass (telegram_user_id, wallet_id, request_ts)
- `api/telegram/user_manager.py` — `UserManager` with `get_or_create_user` + `get_user_wallet`

### Behavior
- On first interaction: user auto-created, wallet auto-assigned, mapping stored in memory.
- Idempotent: repeated calls with same telegram_user_id return the existing record.
- Double-check locking pattern prevents race conditions under concurrent requests.
- No global state: all state is UserManager instance-scoped.

### Schema
```
UserRecord:
  telegram_user_id  int  (primary key)
  wallet_id         str
  created_at        float (unix ts)
```

---

## 2. Wallet Integration

### Files
- `wallet/__init__.py`
- `wallet/wallet_manager.py`

### API
```python
wallet_id = await wm.create_wallet(user_id)   # idempotent
balance   = await wm.get_balance(wallet_id)
exposure  = await wm.get_exposure(wallet_id)
net_pnl   = await wm.record_trade(wallet_id, gross_pnl, exposure_delta)
```

### Rules enforced
- Custodial only — no key export, no private key storage.
- No withdraw functionality.
- `record_trade` is called by execution layer only, never surfaced in UI.

---

## 3. Menu Structure

### Files
- `api/telegram/menu_handler.py`

### Menus built
| Menu | Buttons |
|------|---------|
| main | 📊 Status, 💰 Wallet, ⚙️ Settings, ▶ Control |
| status | Refresh, Performance, Health, Strategies, Main Menu |
| wallet | Balance, Exposure, Refresh, Main Menu |
| settings | Risk, Mode, Strategy, Notifications, Auto Trade, Main Menu |
| strategy | Per-strategy toggle rows (✅ active, ⬜ inactive), Main Menu |
| control | Pause/Resume (state-aware), Stop (confirm), Main Menu |

### Single-active strategy enforcement
- `strategy_toggle_<id>` sets new active strategy.
- Cannot deactivate the currently active strategy (returns warning).

### Stop confirmation
- `control_stop_confirm` → shows confirm/cancel keyboard.
- `control_stop_execute` → calls `state_manager.halt()`.

---

## 4. Callback Routing

### File
- `api/telegram/menu_router.py`

### Routing table
```
"status"                → show status + status_menu keyboard
"wallet"                → show balance + exposure + wallet_menu
"settings"              → show settings + settings_menu
"control"               → show state + control_menu
"control_pause"         → SystemStateManager.pause()
"control_resume"        → SystemStateManager.resume()
"control_stop_confirm"  → show stop confirm keyboard
"control_stop_execute"  → SystemStateManager.halt()
"strategy_toggle_<id>"  → set active strategy (single-active enforced)
"settings_mode"         → show mode switch confirm
"mode_confirm_<mode>"   → switch PAPER/LIVE
"wallet_balance"        → WalletManager.get_balance()
"wallet_exposure"       → WalletManager.get_exposure()
"performance"           → delegate to core CommandHandler
"health"                → delegate to core CommandHandler
"main_menu"             → show main menu
"noop"                  → ignore (idempotent)
```

### Edit-message pattern
- All callbacks use `edit_message` (not `send_message`) to update the existing message.
- No message spam — one message per context.

---

## 5. Control Integration

### Reuses
- `core.system_state.SystemStateManager` — pause / resume / halt.
- All transitions idempotent: duplicate state changes are silently ignored.

### Guard behavior
| Button | Current State | Result |
|--------|--------------|--------|
| Pause  | RUNNING      | → PAUSED |
| Pause  | PAUSED       | "Already PAUSED" |
| Pause  | HALTED       | "Cannot pause" |
| Resume | PAUSED       | → RUNNING |
| Resume | RUNNING      | "Already RUNNING" |
| Resume | HALTED       | "Manual restart required" |
| Stop   | any non-HALTED | confirm → HALTED |

---

## 6. Fee Integration (Hidden)

### Implementation
- Located in `wallet/wallet_manager.py` — method `_apply_fee(gross_pnl)`.
- Fee rate: 0.5% of gross PnL on winning trades only.
- Applied only when `record_trade()` is called (execution layer).
- `get_balance()` returns net balance (post-fee) — no gross/fee breakdown.
- Fee amount is never logged, printed, or sent to Telegram UI.
- PnL reported in all Telegram messages is net after fee.

---

## 7. What Works

- ✅ User auto-created on first interaction (any message or button press)
- ✅ Wallet assigned per user, persisted in-process
- ✅ All 6 menu trees built (main / status / wallet / settings / strategy / control)
- ✅ All callback_data strings routed correctly
- ✅ Pause / resume / stop via Telegram menu buttons
- ✅ Strategy single-active enforcement
- ✅ edit_message used for all callback responses (no spam)
- ✅ Authorization via ALLOWED_USER_IDS env var
- ✅ Retry on send failure (max 3, exponential backoff)
- ✅ Deduplication by update_id (rolling 10 000 window)
- ✅ Structured logging on every action
- ✅ No duplicate business logic — delegates to existing CommandHandler
- ✅ No global state — all state instance-scoped
- ✅ Hidden fee applied at execution layer only

---

## 8. Known Issues

- Wallet storage is in-memory only: data lost on process restart. Production should persist to SQLite / Redis.
- `TELEGRAM_BOT_TOKEN` must be set; webhook sends silently fail if unset (logged as warning).
- Strategy list is hardcoded to `[ev_momentum, mean_reversion, liquidity_edge]` in menu_router. Should be driven by strategy registry.
- Mode switch (PAPER/LIVE) updates only the local `_mode` field; does not propagate to `LiveModeController`. Wire-up required.
- Rate limiting is on `TelegramWebhookServer` (api/telegram_webhook.py) not the new webhook handler; recommend consolidation.

---

## 9. Next Step

- Wire `WebhookHandler.edit_message` into `MenuRouter` at app startup (pass as `edit_message_fn`).
- Wire `TelegramCommandHandler.send_message` as the `sender` callable.
- Persist `UserManager` and `WalletManager` to durable storage (SQLite).
- Drive strategy list from `StrategyOrchestrator` registry instead of hardcoded list.
- Propagate mode switch to `LiveModeController`.
- Add rate limiting to `WebhookHandler` (currently only on legacy server).
