# FORGE-X REPORT — Telegram Inline Enforcement

**Date:** 2026-04-02
**Branch:** feature/forge/telegram-inline-enforcement
**File:** `reports/forge/TELEGRAM_INLINE_ENFORCEMENT.md`

---

## 1. Inline Architecture

All Telegram UI navigation flows through a single `CallbackRouter` that enforces full inline-only mode:

```
/start command
    └─► sendMessage (ONE-TIME — creates the single active message)

Inline button press (callback_query)
    └─► CallbackRouter.route()
            ├─► answer_callback()       — clears Telegram spinner
            ├─► log.info("INLINE_UPDATE", action=cb_data)
            ├─► _dispatch(action)       — returns (text, keyboard)
            └─► _edit_message()         — editMessageText in-place
                    └─► fallback: _send_message() only on edit failure
```

**Key constraint:** Only `/start` (or the bot's welcome handler) ever calls `sendMessage` for the interactive menu. Every subsequent navigation uses `editMessageText` on the same message ID, keeping the chat clean and free of stacking.

---

## 2. Before vs After Behavior

| Scenario | Before | After |
|---|---|---|
| User presses "Settings" button | New message sent → stacks on top | Same message edited in-place |
| User presses "Risk Level" | Another new message → third stack | Same message updated → no stack |
| Error during dispatch | Silent fail or orphan message | Error screen replaces same message |
| Message >48 h old | No fallback → broken UX | Graceful fallback to sendMessage (with log) |
| Legacy UI actions (health/performance) | Sometimes handled, sometimes stacked | Hard-blocked: `RuntimeError("LEGACY UI DISABLED")` |

---

## 3. Code Changes

### `telegram/handlers/callback_router.py`

**Added** `log.info("INLINE_UPDATE", action=cb_data)` immediately after parsing the `action:` prefix and before dispatch — emitted on every valid inline button press:

```python
action = cb_data[len(ACTION_PREFIX):]

log.info("INLINE_UPDATE", action=action)

# Step 2: dispatch
```

**Existing inline flow (unchanged, confirmed correct):**

```python
# Step 3: edit in-place; fallback to send on failure
if chat_id and message_id:
    edited = await self._edit_message(session, chat_id, message_id, text, keyboard)
    if not edited:
        log.warning("callback_edit_failed_sending_new", ...)
        await self._send_message(session, chat_id, text, keyboard)
elif chat_id:
    await self._send_message(session, chat_id, text, keyboard)
```

The `_send_message` path is reached **only** when:
1. `message_id` is missing (edge case — no active message to edit)
2. `_edit_message()` returns `False` (Telegram API rejection after all retries)

Both are logged at `WARNING` level before falling back.

---

## 4. UX Improvement

**Single-message navigation:** The user sees exactly one bot message in the chat at all times. All menu transitions — Status → Settings → Risk Level → back to Main — edit that one message in-place. No visual clutter, no scroll-back required.

**Spinner cleared immediately:** `answer_callback()` is called first, before any dispatch work, so the Telegram loading spinner disappears instantly on button press.

**Back navigation:** Every sub-menu includes an `action:back_main` button that returns to the main screen.

**Menus covered:**
- `/start` → main menu (sendMessage — creates the message)
- `action:status` / `action:refresh` → status screen (editMessageText)
- `action:wallet` / `action:wallet_balance` / `action:wallet_exposure` → wallet screens (editMessageText)
- `action:settings` / `action:settings_risk` / `action:settings_mode` / `action:settings_strategy` / `action:settings_notify` / `action:settings_auto` → settings screens (editMessageText)
- `action:control` / `action:control_pause` / `action:control_resume` / `action:control_stop_confirm` / `action:control_stop_execute` → control screens (editMessageText)
- `action:back_main` / `action:back` / `action:menu` → main screen (editMessageText)

---

## 5. Known Edge Cases

| Edge Case | Handling |
|---|---|
| Message older than 48 h | Telegram rejects `editMessageText` → `_edit_message()` returns `False` → fallback `sendMessage` with `WARNING` log |
| Network timeout on edit | Up to 3 retries with exponential back-off (0.5s, 1s); falls back to `sendMessage` after exhausting |
| Callback without message_id | `elif chat_id:` branch → `sendMessage` (logged at WARNING) |
| Unknown `action:*` value | Returns unknown-action screen with main menu keyboard |
| Legacy `action:health` / `action:performance` / `action:strategies` | Hard-blocked at both route level and dispatch level: `RuntimeError("LEGACY UI DISABLED")` |
| Duplicate button press (no change) | Telegram returns "message is not modified" → treated as success (no duplicate send) |
| `action:noop` | Returns empty string → `if not text: return` — no API call at all |

---

## What's Next

- `/start` command handler should send initial message and store the `message_id` for future inline edits (if bot restart is needed, send a new base message)
- Consider storing per-user `message_id` in Redis so the bot can always edit even after restart
