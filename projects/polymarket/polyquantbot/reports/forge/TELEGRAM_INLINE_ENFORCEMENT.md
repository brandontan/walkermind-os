# FORGE-X REPORT — Telegram Inline Enforcement
**Date:** 2026-04-02
**Branch:** feature/forge/telegram-inline-enforcement
**Role:** FORGE-X

---

## 1. Inline Architecture

```
User sends /start (text command)
    └─ _polling_loop → _send_result → sendMessage
           └─ NEW message created with build_main_menu() keyboard
                  (all buttons have action: prefix)

User clicks any button (callback_query, data = "action:<name>")
    └─ _polling_loop detects action: prefix
           └─ _callback_router.route(session, cq)
                  ├─ 1. answerCallbackQuery()     ← clears spinner
                  ├─ 2. log INLINE_UPDATE(action) ← audit trail
                  ├─ 3. _dispatch(action)         ← handler returns (text, keyboard)
                  ├─ 4. editMessageText()         ← PRIMARY: edits existing message
                  └─ 5. sendMessage() fallback    ← ONLY if message >48h / deleted
```

**Key contract:**
- `action:*` callback → `editMessageText` ONLY
- Non-`action:` callback → `answerCallbackQuery` only (no new message, no stacking)
- Text command (`/start`, `/status`) → `sendMessage` (user explicitly typed it)

---

## 2. Before vs After

### BEFORE (stacking problem)

```
User: /start                        → Bot sends Message #1 (main menu)
User: clicks Settings               → Bot sends Message #2 (settings)
User: clicks Risk Level             → Bot sends Message #3 (risk prompt)
User: clicks Back                   → Bot sends Message #4 (main menu)
```
Result: 4 messages, chat cluttered, confusing UX.

Also: non-`action:` legacy callbacks routed via `CommandRouter → sendMessage`,
each creating a new message.

### AFTER (inline enforcement)

```
User: /start                        → Bot sends Message #1 (main menu)
User: clicks Settings               → Message #1 EDITED (now shows settings)
User: clicks Risk Level             → Message #1 EDITED (now shows risk prompt)
User: clicks Back                   → Message #1 EDITED (back to main menu)
```
Result: 1 message, always updated in-place.

---

## 3. Code Changes

### `telegram/handlers/callback_router.py`

**Added `INLINE_UPDATE` log at route entry** (after action parsed):
```python
log.info("INLINE_UPDATE", action=action, chat_id=chat_id, message_id=message_id)
```

**Added `INLINE_UPDATE` log in `_dispatch`** (replaces `callback_dispatching`):
```python
log.info("INLINE_UPDATE", action=action)
```

**Made try/except inline enforcement explicit in `route()`**:
```python
# Step 3: edit in-place (primary path)
#         fallback to sendMessage ONLY if edit is truly unavailable
try:
    edited = await self._edit_message(session, chat_id, message_id, text, keyboard)
    if not edited:
        await self._send_message(session, chat_id, text, keyboard)
except asyncio.CancelledError:
    raise
except Exception as exc:
    log.error("callback_inline_update_failed", ...)
    await self._send_message(session, chat_id, text, keyboard)
```

---

### `main.py` — `_polling_loop`

**Removed legacy sendMessage callback branches:**

Old branches (REMOVED):
- `cb_data.endswith("_prompt")` → called `_send_result()` → `sendMessage` ❌
- Else fallback → routed via `CommandRouter` → `_send_result()` → `sendMessage` ❌

New callback handling:
```python
if cb_data.startswith("action:"):
    await _callback_router.route(session, cq)   # editMessageText
else:
    # Answer only — NO new message, NO stacking
    await session.post("/answerCallbackQuery", json={
        "callback_query_id": cq["id"],
        "text": "⚠️ Outdated button — send /start to refresh.",
        "show_alert": False,
    })
    log.warning("callback_non_action_ignored", ...)
```

**Cleaned up `_send_result` signature:**

Removed unused `callback_query_id` parameter. `_send_result` now only handles
text command responses (sendMessage for `/start`, `/status`, etc.).

---

## 4. UX Improvement

| Metric | Before | After |
|--------|--------|-------|
| Messages per navigation session | N (one per action) | 1 (always same message) |
| Button click behavior | New message spawned | Existing message edited |
| Chat scroll needed | Yes (messages accumulate) | No (single fixed message) |
| Old button clicks | Spawned new messages | Toast: "use /start to refresh" |
| Logs per callback | `callback_dispatching` | `INLINE_UPDATE` (explicit) |

---

## 5. Known Edge Cases

| Case | Behavior |
|------|----------|
| Message >48h old | `editMessageText` returns 400, fallback to `sendMessage` |
| Message deleted by user | Same as above — fallback to `sendMessage` |
| Bot restarted, old message clicked | Callback answered with toast, no new message |
| `/start` typed | `sendMessage` — correct, creates fresh entry point |
| Multiple users | Each `message_id` is per-user, edits only affect that message |
| No `TELEGRAM_TOKEN` set | Polling loop never starts, no callbacks processed |
| Network timeout on edit | Retried 3× with backoff; falls back to send on exhaustion |

---

## 6. Log Output (Expected)

On every button press:
```json
{"event": "callback_received", "callback_data": "action:status", "chat_id": 123, "message_id": 456}
{"event": "INLINE_UPDATE", "action": "status", "chat_id": 123, "message_id": 456}
{"event": "INLINE_UPDATE", "action": "status"}
{"event": "callback_edit_success", "chat_id": 123, "message_id": 456, "attempt": 1}
```

---

**Status: COMPLETE**
