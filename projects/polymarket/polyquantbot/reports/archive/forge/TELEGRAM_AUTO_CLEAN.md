# FORGE-X — Telegram Auto-Clean Report

**Date:** 2026-04-02  
**Branch:** feature/forge/telegram-auto-clean  
**Status:** ✅ COMPLETE

---

## 1. Cleanup Flow

```
User taps reply keyboard button
        │
        ▼
main.py polling loop receives text update
        │
        ├─► asyncio.create_task(schedule_user_message_delete(...))  ← non-blocking
        │         │
        │         ▼
        │   delete_user_message_later(tg_api, chat_id, message_id)
        │         │
        │         ├─ await asyncio.sleep(0.4)
        │         └─ POST /deleteMessage  →  Telegram API
        │
        └─► _on_text_message(session, chat_id, text)  ← normal flow continues
```

---

## 2. Delay Logic

- Default delay: **0.4 seconds** (within the 0.3–0.5 s spec window)
- Implemented via `asyncio.sleep(delay)` inside the background task
- Configurable via the `delay` parameter of `delete_user_message_later`
- The `schedule_user_message_delete` wrapper always uses the default (0.4 s)

---

## 3. Before vs After UX

| UX Dimension | Before | After |
|---|---|---|
| User message visibility | Persists in chat permanently | Disappears after ~0.4 s |
| Inline message | Edited in-place | Unaffected (different message_id) |
| Chat cleanliness | Reply keyboard presses accumulate | Chat stays clean |
| Bot message | N/A | Never deleted — only user messages |
| Crash risk | N/A | Zero — all errors swallowed |

---

## 4. Files Created / Modified

| File | Action |
|---|---|
| `telegram/utils/__init__.py` | Created — package init |
| `telegram/utils/message_cleanup.py` | Created — `delete_user_message_later` |
| `telegram/handlers/text_handler.py` | Created — `schedule_user_message_delete` |
| `main.py` | Modified — call `schedule_user_message_delete` on reply KB taps |
| `tests/test_telegram_auto_clean.py` | Created — 7 tests (AC-01 – AC-07) |

---

## 5. Edge Cases Handled

- **message_id missing**: `msg.get("message_id")` guard in main.py — no task created if ID absent
- **Delete fails (message already deleted, permissions)**: `except Exception: pass` in cleanup
- **Network error**: Swallowed silently — bot continues normally
- **Inline messages**: Never targeted — only the user's text message_id is passed
- **Bot messages**: Never passed to cleanup — only `msg` (user update) is cleaned
- **asyncio.CancelledError**: Not caught by `except Exception` — propagates correctly

---

## 6. What's Working

- Non-blocking background deletion via `asyncio.create_task`
- 0.4 s delay before delete call
- Structured log event `user_message_deleted` on success
- Inline UI (editMessageText) completely unaffected
- Zero crashes from failed deletes
- 7 unit tests passing

---

## 7. Known Issues

None.

---

## 8. What's Next

- Optional: make delay configurable via env var (`TG_MSG_DELETE_DELAY_S`)
- Optional: extend to `/command` text messages if needed
