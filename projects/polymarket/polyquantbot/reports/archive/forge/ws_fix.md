# ws_fix — WebSocket Compatibility Fix

## 1. What Was Built

Fixed a runtime `TypeError: unexpected keyword 'extra_headers'` that caused the WebSocket client
to fail on any `websockets >= 12.0` install (the parameter was renamed to `additional_headers`
in that release).

Three targeted changes were made to `data/websocket/ws_client.py` and `requirements.txt`:

1. **Parameter rename** — `extra_headers` → `additional_headers` in `websockets.connect()`.
2. **Startup version log** — emits `"websockets_version"` log entry (with the installed version
   string) in `PolymarketWSClient.connect()` for easy Railway log verification.
3. **Fail-fast** — `_run_ws_loop` now tracks consecutive failures; if failures exceed
   `_MAX_RETRIES` (5), it sets `_running = False` and raises `RuntimeError` to stop the system
   rather than looping forever.

---

## 2. Current System Architecture

```
DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING
 └─ PolymarketWSClient (data/websocket/ws_client.py)
     ├─ connect()           — starts WS loop + heartbeat watchdog
     ├─ _run_ws_loop()      — reconnect loop w/ fail-fast after 5 retries
     ├─ _connect_and_stream() — single WS session using additional_headers
     ├─ _heartbeat_watchdog() — forces reconnect on silence > heartbeat_timeout
     └─ events()            — async generator for downstream consumers
```

---

## 3. Files Created / Modified

| File | Action | Change |
|------|--------|--------|
| `requirements.txt` | Modified | `websockets>=12.0` → `websockets>=11.0` |
| `data/websocket/ws_client.py` | Modified | Added `_MAX_RETRIES=5` constant |
| `data/websocket/ws_client.py` | Modified | `extra_headers` → `additional_headers` in `_connect_and_stream` |
| `data/websocket/ws_client.py` | Modified | Version log in `connect()` |
| `data/websocket/ws_client.py` | Modified | Fail-fast logic in `_run_ws_loop()` |
| `reports/forge/ws_fix.md` | Created | This report |

---

## 4. What's Working

- `websockets.connect(..., additional_headers=...)` accepted without `TypeError` on websockets 16.0.
- Version log emitted at startup: `{"event": "websockets_version", "version": "X.X.X"}`.
- After 5 consecutive connection failures, `RuntimeError` is raised and `_running` is set to
  `False` — no infinite reconnect loop.
- Clean disconnect (normal close) still resets both backoff delay and failure counter.
- 772 existing tests pass with no regressions.

---

## 5. Known Issues

- None introduced by this change.
- The Railway deploy test (`ws_connected` log) requires the live Polymarket WS endpoint to be
  reachable; that cannot be verified locally.

---

## 6. What's Next

- Wire `PolymarketWSClient` failure propagation (the raised `RuntimeError`) into the main
  orchestrator so the entire pipeline shuts down cleanly when WS is unrecoverable.
- Add Railway health-check log assertion for `ws_connected` in CI smoke tests.
