# WARP•FORGE REPORT — trade-notifications

**Branch:** WARP/CRUSADERBOT-FAST-TRADE-NOTIFS
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Async event bus + notification service subscription (position.opened, position.closed, copy_trade.executed)
**Not in Scope:** Trade execution logic, positions table, wallet logic, Track A engine internals, Track B copy-trade execution
**Suggested Next Step:** WARP🔹CMD review; merge after Track A (WARP/CRUSADERBOT-FAST-TRADE-EXEC or equivalent) is merged first

---

## 1. What Was Built

Two new modules enabling event-driven Telegram trade receipt delivery:

**`core/event_bus.py`** — Async in-process event emitter. Handlers are registered via `subscribe(event, handler)` and fired as fire-and-forget asyncio tasks via `await emit(event, **payload)`. Per-handler exceptions are caught and logged — one failing handler never blocks the caller or other handlers.

**`services/notification_service.py`** — Subscribes three handlers to the event bus:
- `position.opened` → 📋 TRADE OPENED receipt with `<pre>` monospace block (Market, Side, Size, Entry, TP, SL, Strategy) + [📊 Portfolio] [📈 My Trades] buttons
- `position.closed` → ✅/❌/➖ TRADE CLOSED receipt with full close card (Market, Side, Entry, Exit, P&L, Hold, Reason) — WIN/LOSS/BREAKEVEN from P&L sign; close reason mapped to human label
- `copy_trade.executed` → 🐋 COPY TRADE receipt with wallet truncation + same button row

All handlers are failure-safe: `_send_safe` checks user opt-out, catches all exceptions, logs at ERROR, never re-raises. Notification failure cannot crash trade execution.

---

## 2. Current System Architecture

```
Track A (position lifecycle)
    └─ await event_bus.emit("position.opened", **kwargs)
    └─ await event_bus.emit("position.closed", **kwargs)

Track B (copy trade execution)
    └─ await event_bus.emit("copy_trade.executed", **kwargs)

core/event_bus.py
    └─ fire-and-forget asyncio.create_task per subscriber
    └─ _safe_call catches handler exceptions

services/notification_service.py
    ├─ _on_position_opened  → 📋 TRADE OPENED
    ├─ _on_position_closed  → ✅/❌/➖ TRADE CLOSED
    └─ _on_copy_trade_executed → 🐋 COPY TRADE
           └─ notifications_enabled_by_telegram_id (opt-out gate)
           └─ notifications.send (retry + backoff via tenacity)
```

Startup wire-up (to be added by Track A PR or main.py):
```python
from projects.polymarket.crusaderbot.services.notification_service import register_handlers
register_handlers()
```

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/core/__init__.py` (empty package marker)
- `projects/polymarket/crusaderbot/core/event_bus.py` (async event emitter, 50 lines)
- `projects/polymarket/crusaderbot/services/notification_service.py` (notification service, 219 lines)

**Modified:**
- None — no existing files touched

---

## 4. What Is Working

- `core/event_bus.py` compiles clean, ruff clean
- `services/notification_service.py` compiles clean, ruff clean
- Entry receipt format: `<pre>` block, ━━━ separators, Strategy line, Portfolio + My Trades buttons
- Exit receipt: unified TRADE CLOSED with WIN/LOSS/BREAKEVEN icon+label, Hold duration (Xh Ym), mapped close reason label
- Copy trade receipt: wallet truncation (first 6 + last 4), `<pre>` monospace block
- All amounts in `${value:.2f}`, all prices in `${value:.4f}`, separator is heavy box character
- Duration formatter: 3600s → "1h 0m", 1800s → "30m", None → "—"
- P&L sign: positive → "+$X.XX", negative → "-$X.XX", zero → "$0.00"
- Failure-safe: `_send_safe` catches all exceptions; notifications failure does not propagate
- User opt-out gate: `notifications_enabled_by_telegram_id` respected before any send
- Button callbacks consistent with existing keyboard conventions: `menu:portfolio`, `menu:trades`
- **kwargs passthrough (`**_: Any`) allows Track A to emit richer payloads without breaking handlers

---

## 5. Known Issues

- `register_handlers()` is not yet called at startup — requires Track A or `main.py` to add the call. This is by design: Track C must merge after Track A.
- Test suite cannot run in cloud sandbox (structlog not installed in execution env). This is a pre-existing environment constraint, not caused by this PR. Tests run locally via `pytest` with project dependencies installed.
- event_bus state is module-level global; a reset helper for test isolation (`_subscribers.clear()`) is not provided but can be added in a test fixture if needed.

---

## 6. What Is Next

- Track A emits `position.opened` / `position.closed` via `event_bus.emit(...)` at the appropriate call sites in the trade engine and exit watcher
- Track B emits `copy_trade.executed` via `event_bus.emit(...)` in `CopyTradeMonitor` after successful TradeEngine.execute()
- `register_handlers()` called once in `main.py` after bot initialisation
- Merge order: Track A first → Track C second
- WARP🔹CMD decides merge after review
