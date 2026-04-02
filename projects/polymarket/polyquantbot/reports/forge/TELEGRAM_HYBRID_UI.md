# FORGE-X REPORT — Telegram Hybrid UI

**Task:** `feature/forge/telegram-hybrid-ui`  
**Date:** 2026-04-02  
**Status:** ✅ COMPLETE

---

## 1. What Was Built

A hybrid Telegram UI combining:

- **Reply keyboard** (bottom persistent menu) — navigation trigger only
- **Inline keyboard** — all dynamic content via `editMessageText`

The system maintains a single active inline message per chat that is edited
in-place on every navigation action, regardless of whether the user pressed an
inline button or a reply keyboard button.

---

## 2. Hybrid Architecture

```
User presses reply keyboard button (e.g. "📊 Trade")
        │
        ▼
Telegram sends text message "📊 Trade"
        │
        ▼
_polling_loop detects text ∈ REPLY_MENU_MAP
        │
        ▼
_on_text_message(session, chat_id, text)
        │  maps "📊 Trade" → action "status"
        │
        ├── Has active inline message_id?
        │     YES → synthesise callback_query → CallbackRouter.route()
        │                                              │
        │                                              ▼
        │                                       editMessageText ✅
        │
        └── NO → sendMessage (inline keyboard) → track message_id
```

```
User presses inline button (e.g. [💰 Wallet])
        │
        ▼
Telegram sends callback_query  data="action:wallet"
        │
        ▼
CallbackRouter.route() → editMessageText ✅
```

---

## 3. Reply vs Inline Separation

| Concern | Reply Keyboard | Inline Keyboard |
|---------|---------------|-----------------|
| Purpose | Navigation trigger | Dynamic content + actions |
| Visibility | Always visible (bottom) | Single message, edited in-place |
| API method | `sendMessage` (once, on /start) | `editMessageText` (on every action) |
| Logic | None — maps to action string only | All screen logic lives here |
| Duplication | Zero — reuses callback system | Canonical source of truth |

---

## 4. Files Created / Modified

### Created

- `telegram/ui/reply_keyboard.py`  
  - `get_main_reply_keyboard()` → `ReplyKeyboardMarkup` dict  
  - `get_reply_keyboard_remove()` → `ReplyKeyboardRemove` dict  
  - `REPLY_MENU_MAP: dict[str, str]` — button label → action name  

### Modified

- `main.py` — `_polling_loop()`:
  - Import `get_main_reply_keyboard`, `REPLY_MENU_MAP` from `reply_keyboard`
  - `_send_result()`: now parses `sendMessage` response to track `message_id`
    → stores in `_inline_msg_ids[chat_id]`
  - `_on_text_message()`: new coroutine — handles reply keyboard button presses
    → synthesises callback_query with tracked `message_id` → `CallbackRouter.route()`
    → fallback: sends new inline message if no tracked `message_id` exists
  - `/start` handling: sends `ReplyKeyboardMarkup` message before sending inline content
  - Text routing: intercepts `REPLY_MENU_MAP` labels before ignoring non-`/` text

---

## 5. UX Improvements

1. **Persistent bottom menu** — always visible; never disappears after actions
2. **Single active message** — inline content always edited in-place (no stacking)
3. **Consistent navigation** — reply keyboard and inline buttons produce identical results
4. **Graceful fallback** — if bot restarts and loses `message_id`, clicking a reply
   button creates a fresh inline message (one-time, then edits from then on)

---

## 6. Mapping Logic

```python
REPLY_MENU_MAP = {
    "📊 Trade":    "status",
    "💰 Wallet":   "wallet",
    "⚙️ Settings": "settings",
    "▶ Control":  "control",
}
```

Each value is a valid `action:<name>` routed through `CallbackRouter._dispatch()`.

---

## 7. Known Limitations

- `_inline_msg_ids` lives in memory only; restarts clear tracking (one extra
  sendMessage on first reply keyboard press after restart — acceptable)
- Reply keyboard is sent as a separate message on `/start` (2 messages total on
  first launch); all subsequent interactions edit the single inline message
- `ReplyKeyboardRemove` helper exists in `reply_keyboard.py` but is not wired to
  a command by default (future: `/hidemenu` command)

---

## 8. What's Next

- Optional: `/hidemenu` → `ReplyKeyboardRemove()` for power users
- Optional: persist `_inline_msg_ids` in Redis for cross-restart continuity
