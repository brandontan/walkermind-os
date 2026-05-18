# WARP•FORGE Report — crusaderbot-webtrader-ws

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: SSE real-time push to WebTrader frontend; polling removal
Not in Scope: WebSocket upgrade, new trading features, pg_notify channel changes
Suggested Next Step: WARP🔹CMD review; deploy to Fly.io and verify Network tab shows single long-lived /api/stream connection

---

## 1. What Was Built

Replaced all browser-side polling in WebTrader with Server-Sent Events (SSE) push.

- Removed all `setInterval`/`setTimeout` polling from `DashboardPage.tsx` and `PortfolioPage.tsx`
- Extended the existing SSE backend (`webtrader/backend/sse.py`) with an event_bus bridge that pushes events when positions open/close and when the scanner ticks
- Added four new SSE event types: `position_opened`, `position_closed`, `portfolio_update`, `scanner_tick`
- Frontend `useSSE` hook updated to route all four new event types
- Both pages now subscribe to the new event types and call `load()` immediately on receipt
- `market_signal_scanner.run_job()` emits `scanner.tick` via event_bus after each scan cycle

---

## 2. Current System Architecture

```
Scanner (scheduler) ──emit("scanner.tick")──► event_bus
                                                  │
Trade Engine ──emit("position.opened")──────────► event_bus
             ──emit("position.closed")──────────► │
                                                  ▼
                         webtrader/backend/sse.py:register_event_bus_handlers()
                                  │
                    ┌─────────────┴──────────────┐
                    │                            │
            _push_to_user(user_id)         _push_broadcast()
                    │                            │
                    ▼                            ▼
              user's Queue                all user Queues
                    │
                    ▼
          EventSourceResponse (GET /api/web/stream)
                    │
             EventSource (browser)
                    │
            useSSE hook (React)
                    │
            DashboardPage / PortfolioPage
            → load() on event receipt
```

pg LISTEN/NOTIFY path remains active for `cb_positions`, `cb_portfolio`, etc.
event_bus bridge is additive — events can arrive via both paths without duplication
because both trigger a full re-fetch (`load()`) rather than applying partial diffs.

telegram_user_id → user_id mapping: populated when user connects to SSE stream.
The JWT contains both `user_id` (UUID) and `telegram_id` (int). The `stream_for_user`
function registers the mapping on connect and cleans it up on disconnect.

---

## 3. Files Created / Modified

Modified:
- `projects/polymarket/crusaderbot/webtrader/backend/sse.py`
  - Added `_telegram_to_user_id` reverse map
  - Added `_push_to_user()`, `_push_broadcast()` direct push helpers
  - Added `_on_position_opened_sse()`, `_on_position_closed_sse()`, `_on_scanner_tick_sse()` event_bus handlers
  - Added `register_event_bus_handlers()` registration function
  - Updated `stream_for_user(user_id, telegram_user_id)` signature to register/clean up reverse map

- `projects/polymarket/crusaderbot/webtrader/backend/router.py`
  - `sse_stream` passes `user["telegram_id"]` to `stream_for_user`

- `projects/polymarket/crusaderbot/main.py`
  - Calls `webtrader_sse.register_event_bus_handlers()` at startup after `register_notification_handlers()`

- `projects/polymarket/crusaderbot/jobs/market_signal_scanner.py`
  - `run_job()` emits `scanner.tick` via event_bus after updating `_scanner_state`
  - Exception caught and logged — scanner return value is unaffected

- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/sse.ts`
  - `EVENT_TYPES` extended: `position_opened`, `position_closed`, `portfolio_update`, `scanner_tick`

- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/DashboardPage.tsx`
  - Removed polling `useEffect` (10s setTimeout loop)
  - `useSSE` handler map extended with `position_opened`, `position_closed`, `portfolio_update`, `scanner_tick`

- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx`
  - Removed polling `useEffect` (10s setTimeout loop)
  - `useSSE` handler map extended with `position_opened`, `position_closed`, `portfolio_update`

---

## 4. What Is Working

- Single long-lived `GET /api/web/stream` EventSource connection per browser tab
- Auto-reconnect with exponential backoff built into `useSSE` (1s → 30s cap)
- 25-second ping keepalive to prevent proxy/Fly.io idle timeout
- event_bus → SSE path: when position.opened/closed fires, user's dashboard and portfolio update instantly without any poll cycle
- Scanner tick broadcast: when scanner completes a cycle, all connected dashboards refresh
- pg LISTEN/NOTIFY path preserved for order fills, settings changes, and system alerts
- No `setInterval`, no `setTimeout` polling anywhere in DashboardPage or PortfolioPage

---

## 5. Known Issues

- event_bus `position.opened` / `position.closed` emitters are not yet confirmed wired in all trade execution paths (the notification_service subscribes but some execution paths may not emit yet — this was a pre-existing gap, not introduced here)
- SSE event_bus bridge only works for users currently connected; not a delivery guarantee
- telegram_user_id → user_id mapping is per-process in-memory only; multi-worker Fly.io deploy requires Redis pub/sub for cross-worker routing (paper mode single-instance is fine)

---

## 6. What Is Next

- WARP🔹CMD review and Fly.io deploy
- Verify Network tab shows single `/api/stream` connection, no repeated API requests
- If multi-worker needed: move `_telegram_to_user_id` + SSE fan-out to Redis pub/sub (separate lane)
- Wire `position.opened` / `position.closed` event_bus emits from trade execution paths if not yet confirmed (separate audit lane)
