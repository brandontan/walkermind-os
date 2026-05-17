# WARP•FORGE Report — wire-notification-handlers

Validation Tier: MINOR
Claim Level: NARROW INTEGRATION
Validation Target: main.py lifespan — register_notification_handlers() wiring
Not in Scope: notification_service logic, event_bus implementation, Telegram delivery
Suggested Next Step: WARP🔹CMD review and merge

---

## 1. What was built

Wired `notification_service.register_handlers()` into the bot startup lifespan in `main.py`.
Call site: after `await bot_app.start()`, before polling/webhook block.
This activates the three event-bus subscriptions — `position.opened`, `position.closed`,
`copy_trade.executed` — so Telegram trade receipts fire on every trade event.

## 2. Current system architecture

`notification_service.register_handlers()` calls `subscribe()` from `core.event_bus`
for each of the three trade events. Handlers are async and use `notifications.send()`.
`notifications.set_bot()` is called at line 87, before `register_notification_handlers()`
at line 91, so the bot reference is always ready when a handler fires.

Pipeline: event emitter → event_bus.publish() → subscribed handler → `_send_safe()` → `notifications.send()` → Telegram.

## 3. Files created / modified

- Modified: `projects/polymarket/crusaderbot/main.py`
  - Line 23: added `from .services.notification_service import register_handlers as register_notification_handlers`
  - Line 91: added `register_notification_handlers()` call after `await bot_app.start()`

## 4. What is working

- `python3 -m compileall projects/polymarket/crusaderbot` — clean, zero errors
- `ruff check projects/polymarket/crusaderbot/main.py` — All checks passed
- Import uses alias `register_notification_handlers` to avoid name collision with
  the existing `register_handlers` alias from `bot.dispatcher` (line 22)

## 5. Known issues

None.

## 6. What is next

WARP🔹CMD review and merge. No SENTINEL required (Tier: MINOR).
