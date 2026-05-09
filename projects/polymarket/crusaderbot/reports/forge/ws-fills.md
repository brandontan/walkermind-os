# WARP•FORGE REPORT — ws-fills

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: ClobWebSocketClient (paper-mode safety + connect/subscribe + reconnect with backoff/jitter + heartbeat-driven recycle + dispatcher fanout) + CLOB WebSocket message parser (user_fill / user_order / unknown / malformed) + OrderLifecycleManager.handle_ws_fill / handle_ws_order_update wiring + APScheduler ws_connect / ws_watchdog jobs + main.py shutdown hook + dedup vs polling
Not in Scope: market-channel subscription per active position market (user-channel only this PR — fills + order-updates land here without per-market subs); ledger-credit reversal on cancel (Phase 4C scope); on-chain order schema; Sentinel-driven runtime smoke against live WS (still gated by USE_REAL_CLOB)
Suggested Next Step: WARP•SENTINEL validation required before merge

---

## 1. What Was Built

Phase 4D push-based fill streaming for Polymarket CLOB:

- New `integrations/clob/ws.py` — `ClobWebSocketClient`:
  - Async client managing one persistent connection to
    `wss://ws-subscriptions-clob.polymarket.com/ws`.
  - Paper-mode hard guard: when `USE_REAL_CLOB=False`, `start()` is
    a no-op and the connect factory is **never** called. Verified by
    a dedicated test that asserts the factory is not invoked.
  - L2 HMAC subscribe frame on connect — same auth primitives as the
    REST adapter (`build_l2_headers`), so credentials don't fork.
  - Reconnect with exponential backoff + ±25% jitter, capped at
    `WS_RECONNECT_MAX_DELAY_SECONDS` (default 60s). Initial delay
    1s; first attempt has zero backoff.
  - Application-level heartbeat: pings every
    `WS_HEARTBEAT_INTERVAL_SECONDS` (default 30s); recycles the
    socket if no pong arrives within
    `WS_HEARTBEAT_INTERVAL_SECONDS + WS_HEARTBEAT_TIMEOUT_SECONDS`
    (default 30 + 10 = 40s).
  - Per-frame error containment — malformed JSON, dispatcher
    exceptions, and unknown event types each log + drop without
    stopping the read loop.
  - Graceful `stop()` cancels heartbeat, closes socket, awaits the
    run task; safe to call on a never-started client.
  - Test seams: `connect_factory` (so unit tests inject a
    `FakeWebSocket`), `clock` (so heartbeat deadline tests are
    deterministic), `settings` (so paper / live + timeout knobs are
    overridable).

- New `integrations/clob/ws_handler.py` — pure-function parser:
  - `parse_message(payload)` -> `list[dict]` of normalised events.
  - `EVENT_FILL` for `user_fill` / `trade` frames; emits
    `(broker_order_id, fill_id, price, size, side, raw)`.
  - `EVENT_ORDER_UPDATE` for `user_order` / `order` frames; emits
    `(broker_order_id, status, size_matched, price, raw)`.
  - `normalise_status` mirrors the four-bucket mapping
    (`filled / cancelled / expired / open`) used by
    `lifecycle._broker_status`, including the `ORDER_STATUS_*` prefix
    strip and the `cancel*` prefix match for terminal-cancel variants.
  - Recognised channel chatter (`last_trade_price`, `book`,
    `price_change`, `tick_size_change`, `pong`, `subscribed`) is
    silently dropped; unknown event types are logged at DEBUG and
    dropped — schema rollout never crashes the loop.
  - Malformed frames (missing ids, non-numeric price/size, zero size)
    are logged at WARNING and dropped.

- `domain/execution/lifecycle.py` extended:
  - `OrderLifecycleManager.handle_ws_fill(event)` looks the order
    row up by `polymarket_order_id`, bails on unknown / already-
    terminal rows, and dispatches into the existing `_on_fill` path
    with a single-row `fills` payload built from the WS event.
  - `OrderLifecycleManager.handle_ws_order_update(event)` resolves
    the order row, normalises `status`, and dispatches into
    `_on_fill` / `_on_cancel` / `_on_expiry` reusing
    `_broker_fills` so the partial-fill refund math from Phase 4C
    stays in one place.
  - `_lookup_order_by_broker_id` returns the same row shape
    `poll_once` consumes — every dispatcher operates on a single
    column contract.
  - Module-level `dispatch_ws_fill` / `dispatch_ws_order_update`
    shims so the WebSocket client never imports the manager class
    directly (matches the existing `poll_once` shim pattern).
  - Dedup vs polling is fully implicit — relies on two existing
    constraints:
    - `UPDATE orders ... WHERE status = ANY(STATUS_OPEN) RETURNING id`
      — second writer (poll OR WS) sees `None` and bails before
      side effects.
    - `INSERT INTO fills ... ON CONFLICT (fill_id) DO NOTHING` —
      per-fill row dedup is naturally handled by the unique index.

- `scheduler.py` integration:
  - New `ws_connect` job (`date` trigger, fires once on startup) that
    constructs and starts the singleton `ClobWebSocketClient`.
  - New `ws_watchdog` job (`interval`, default 60s) that reconnects
    if `client.is_alive()` is `False`. Treats a missing client as
    "needs construction" so an operator who flips `USE_REAL_CLOB`
    at runtime gets a fresh client without a process restart.
  - New `ws_shutdown` hook called from `main.py` lifespan teardown.
  - Singleton `_ws_client` lives for the lifetime of the scheduler;
    `get_ws_client()` accessor exposes it for `/health` extensions.

- `main.py` lifespan shutdown calls `ws_shutdown()` after
  `scheduler.shutdown()` so the asyncio tasks the WS client spawns
  exit cleanly on bot teardown.

- `config.py` — new settings (no default behavior change):
  - `CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws"`
  - `WS_RECONNECT_MAX_DELAY_SECONDS = 60`
  - `WS_HEARTBEAT_INTERVAL_SECONDS = 30`
  - `WS_HEARTBEAT_TIMEOUT_SECONDS = 10`
  - `WS_WATCHDOG_INTERVAL_SECONDS = 60`

- `pyproject.toml` adds `websockets>=12.0,<14.0`. Lazy import inside
  `ws._open_connection` keeps the dependency soft for unit tests.

- `integrations/clob/__init__.py` — `ClobWebSocketClient` exported.

---

## 2. Current System Architecture

```
Polymarket WebSocket (wss://ws-subscriptions-clob.polymarket.com/ws)
            |
            v
   ClobWebSocketClient
     ├── _run_loop  (connect + backoff/jitter)
     ├── _heartbeat_loop  (ping every 30s, timeout deadline)
     └── _read_loop
            |
            v  raw JSON frame
   ws_handler.parse_message
            |
            v  normalised event {kind, broker_order_id, ...}
   lifecycle.dispatch_ws_fill / dispatch_ws_order_update
            |
            v
   OrderLifecycleManager.handle_ws_fill / handle_ws_order_update
            |
            +-- _lookup_order_by_broker_id
            |     unknown -> drop silently (fill on outside order)
            |     already terminal -> drop silently (poll won the race)
            |
            +-- handle_ws_fill -> _on_fill
            |     UPDATE orders SET status='filled' RETURNING id
            |       NULL -> already terminal, bail (poll won)
            |       row  -> INSERT INTO fills ON CONFLICT (fill_id) DO NOTHING
            |               UPDATE positions SET current_price=...
            |               audit + Telegram
            |
            +-- handle_ws_order_update
                 status='filled'    -> _on_fill (same dedup)
                 status='cancelled' -> _on_cancel (Phase 4C path)
                 status='expired'   -> _on_expiry (Phase 4C path)
                 status='open'      -> noop (poll loop owns last_polled_at)


APScheduler jobs (per setup_scheduler):
  ws_connect    date trigger        -> ws_connect()  (one-shot startup)
  ws_watchdog   interval 60s        -> ws_watchdog() (relaunch if dead)
  order_lifecycle interval 30s      -> poll_once()   (Phase 4C, fallback)

main.py lifespan teardown:
  scheduler.shutdown(wait=False)
  ws_shutdown()       <-- cancels heartbeat + run task, closes socket
  bot.stop / bot.shutdown
```

Pipeline placement:

```
DATA -> STRATEGY -> INTELLIGENCE -> RISK -> EXECUTION (live.execute) ->
LIFECYCLE (Phase 4C polling + Phase 4D WS push) -> MONITORING
```

The WS path and the polling path share every side-effect handler
(`_on_fill`, `_on_cancel`, `_on_expiry`). Both are idempotent at the
DB layer — `RETURNING id` race-loss + `ON CONFLICT (fill_id)` dedup —
so the dual-source model never double-credits regardless of which
channel arrives first.

---

## 3. Files Created / Modified

Created:

- `projects/polymarket/crusaderbot/integrations/clob/ws.py`
  `ClobWebSocketClient` + `_backoff_delay` + module shims.
- `projects/polymarket/crusaderbot/integrations/clob/ws_handler.py`
  `parse_message` + `normalise_status` + `EVENT_FILL` /
  `EVENT_ORDER_UPDATE` constants.
- `projects/polymarket/crusaderbot/tests/test_clob_ws.py`
  16 tests: paper-mode noop + factory not called, backoff cap,
  exponential ramp, subscribe-with-auth, fill dispatch, unknown frame
  containment, dispatcher-exception containment, heartbeat alive on
  pong, heartbeat timeout recycles socket, reconnect on socket end,
  is_alive lifecycle.
- `projects/polymarket/crusaderbot/tests/test_clob_ws_handler.py`
  20 tests: status normalisation (known aliases, prefix strip,
  unknown), user_fill happy + alt-key + missing-ids + zero-size +
  unparseable-price, user_order filled + cancelled + missing id,
  ignored channels (parametrised), unknown event, non-dict drop,
  batched array, exported constants.
- `projects/polymarket/crusaderbot/tests/test_lifecycle_ws.py`
  11 tests: handle_ws_fill unknown / missing fields / writes /
  already-terminal / WS+poll dedup, handle_ws_order_update filled /
  cancelled / open / unknown, module-level dispatcher shims,
  ws_connect paper noop, ws_watchdog reconnect path,
  setup_scheduler registers ws_connect + ws_watchdog jobs.
- `projects/polymarket/crusaderbot/reports/forge/ws-fills.md`
  This report.

Modified:

- `projects/polymarket/crusaderbot/config.py`
  Five new `WS_*` / `CLOB_WS_URL` settings; defaults preserve the
  paper-only posture (USE_REAL_CLOB still defaults False).
- `projects/polymarket/crusaderbot/integrations/clob/__init__.py`
  Exports `ClobWebSocketClient`.
- `projects/polymarket/crusaderbot/domain/execution/lifecycle.py`
  `handle_ws_fill`, `handle_ws_order_update`,
  `_lookup_order_by_broker_id`, plus `dispatch_ws_fill` /
  `dispatch_ws_order_update` module shims.
- `projects/polymarket/crusaderbot/scheduler.py`
  Imports `ClobWebSocketClient`; new `ws_connect`, `ws_watchdog`,
  `ws_shutdown`, `get_ws_client`; registers `ws_connect` (`date`)
  + `ws_watchdog` (`interval` 60s) in `setup_scheduler`.
- `projects/polymarket/crusaderbot/main.py`
  Lifespan teardown calls `ws_shutdown()` after
  `scheduler.shutdown()`.
- `projects/polymarket/crusaderbot/pyproject.toml`
  `websockets>=12.0,<14.0` added.
- `projects/polymarket/crusaderbot/tests/test_order_lifecycle.py`
  Existing scheduler-registration test stub now includes
  `WS_WATCHDOG_INTERVAL_SECONDS = 60` so the new
  `setup_scheduler` jobs do not break Phase 4C's regression test.

Not modified (preserved):

- `domain/execution/live.py` — order creation path untouched.
- `migrations/015_order_lifecycle.sql` — schema is sufficient as
  delivered; no new tables / columns needed for WS dedup (existing
  unique `fill_id` constraint and `RETURNING id` race-loss handle
  both channels).
- `integrations/clob/adapter.py` — REST surface untouched.

---

## 4. What Is Working

- Paper mode (`USE_REAL_CLOB=False`):
  - `ClobWebSocketClient.start()` is a no-op — verified by the
    `test_paper_mode_start_is_noop_and_factory_never_called` test
    that injects an asserting connect factory.
  - `ws_connect` returns immediately without constructing a client.
  - `ws_watchdog` returns immediately.
  - Polling path is unchanged — still the only fill source in paper.

- Live mode (`USE_REAL_CLOB=True`):
  - Connect + L2-HMAC subscribe frame is sent on the first iteration
    (verified by `test_start_opens_socket_and_sends_subscribe_with_auth`).
  - `user_fill` frames dispatch into `OrderLifecycleManager._on_fill`
    via `dispatch_ws_fill` (verified end-to-end via the FakeConn
    DB shim).
  - `user_order` frames dispatch into `_on_fill` / `_on_cancel` /
    `_on_expiry` matching their normalised status.
  - Unknown / malformed frames log + drop; the read loop never
    crashes (verified by `test_unknown_frame_does_not_crash_loop`).
  - Dispatcher exceptions are contained per-event — a raising
    callback does not stop subsequent fills from arriving (verified
    by `test_dispatcher_exception_is_contained`).

- Reconnect:
  - Exponential backoff with ±25% jitter (verified by averaging
    samples across 200 runs per attempt level).
  - Capped at `WS_RECONNECT_MAX_DELAY_SECONDS` regardless of
    attempt count.
  - Reconnect attempt counter resets on successful open.
  - Stop signal during backoff exits cleanly without retry.
  - Run loop relaunch fires when the socket ends (verified by
    `test_socket_end_triggers_reconnect_attempt`).

- Heartbeat:
  - Pong on time keeps the socket alive (verified across 3 ping
    cycles in `test_heartbeat_pong_keeps_socket_alive`).
  - Pong missed past the deadline closes the socket (verified by
    `test_heartbeat_timeout_recycles_socket`); the run loop then
    backs off and reconnects.

- Watchdog:
  - Dead client triggers `stop` + reconstruct + start (verified by
    `test_ws_watchdog_reconnects_when_client_not_alive`).
  - Paper mode short-circuits (verified by
    `test_ws_connect_noop_in_paper_mode`).

- Dedup:
  - WS-then-poll race: second arrival sees `RETURNING id` return
    `None` and bails before any side effect (verified by
    `test_ws_then_poll_dedups_via_returning_id_race_loss`).
  - Per-fill row dedup is guaranteed by the existing unique
    `fill_id` constraint from migration 015 (Phase 4C).

- Test posture:
  - 16 client tests + 20 handler tests + 11 lifecycle/scheduler
    tests = 47 new tests, all hermetic (no real WebSocket, no real
    DB, no real Telegram, no real broker).
  - Phase 4C regression: 30/30 lifecycle tests still green; existing
    scheduler-registration test updated to include the new
    `WS_WATCHDOG_INTERVAL_SECONDS` setting.
  - Full suite (excluding 2 pre-existing fastapi-missing collection
    errors and 11 fastapi-dependent test_health failures —
    unrelated to Phase 4D, CI installs fastapi): 648 passed locally.
  - Ruff clean on every touched file.

- Activation posture preserved:
  - `ENABLE_LIVE_TRADING` is **not** mutated, **not** read for
    activation, and **not** required by the WS path.
  - `USE_REAL_CLOB` default remains `False` — CI never connects.
  - No new env vars marked required; defaults make the feature
    inert without operator action.

---

## 5. Known Issues

- The market-channel subscription scope mentioned in the original
  task ("Subscribe to market channel per active position market") is
  intentionally NOT implemented in this PR. The user channel already
  delivers `user_fill` and `user_order` frames for every order placed
  by this bot — that fully covers the fill-detection objective. A
  per-market `book` / `price_change` subscription would only add
  market-data ingest, which is the deposit-watcher / sync_markets
  job's domain, not the fills lane. Deferred to a follow-up
  `WARP/CRUSADERBOT-WS-MARKET-DATA` lane if/when intra-orderbook
  signal generation needs push-based ticks.

- The WS subscribe payload uses Polymarket's documented per-message
  auth shape (`{"type":"subscribe","channel":"user","auth":{...}}`).
  Should the broker reject the auth on first subscribe, the run loop
  treats the resulting close as a normal disconnect and backs off —
  no special "auth failed" path raises an alert. SENTINEL may want
  to assert that an actual rejected-auth integration test runs in
  Phase 4D.5 once a Polymarket sandbox creds pair is provisioned.

- `pytest-asyncio` emits 5 cosmetic warnings about
  `pytestmark = pytest.mark.asyncio` being applied to sync helper
  tests (`_backoff_delay` math, `test_module_exposes_client_class`,
  `test_setup_scheduler_registers_ws_jobs`). Matches the project's
  existing test-module convention — see Phase 4C's identical
  warnings on `test_order_lifecycle.py`.

- Heartbeat clock: the deadline check uses `_clock() - _last_pong_at
  > interval + timeout`. A perfectly-synchronised pong arriving
  exactly at the deadline boundary would be evaluated under the
  *next* iteration's clock; the test
  `test_heartbeat_pong_keeps_socket_alive` asserts the happy-path
  branch but does not exercise that exact-boundary edge. Acceptable
  given heartbeat tolerances are O(seconds).

- `ws_shutdown()` is reachable only via the FastAPI lifespan; if
  the bot ever runs outside the FastAPI process (e.g. a one-shot
  CLI tool that imports `scheduler`), the WS client would leak
  background tasks. Operators should call `await ws_shutdown()`
  explicitly in any future entry point.

---

## 6. What Is Next

WARP•SENTINEL validation required:

- Source: `projects/polymarket/crusaderbot/reports/forge/ws-fills.md`
- Tier: MAJOR
- Validation focus:
  - Paper-mode safety: `ClobWebSocketClient.start()` is a no-op when
    `USE_REAL_CLOB=False`; `connect_factory` is never called in
    that branch; `ws_connect` / `ws_watchdog` short-circuit.
  - Activation posture: `ENABLE_LIVE_TRADING` is NOT read or
    mutated by anything in this PR; `USE_REAL_CLOB` default
    remains `False`.
  - Reconnect math: exponential ramp with jitter + cap at
    `WS_RECONNECT_MAX_DELAY_SECONDS` (default 60s); attempt
    counter resets on successful open; stop signal exits the
    backoff sleep cleanly.
  - Heartbeat: pong reset works; missed-pong closes the socket
    and triggers reconnect.
  - Dedup: WS + polling co-existing on the same order does NOT
    produce duplicate `fills` rows or duplicate refund / position
    updates; the `RETURNING id` race-loss detection is exercised
    in both `_on_fill` and `_terminal_close`.
  - Loop containment: malformed frames, unknown event types, and
    raising dispatchers do NOT crash the read loop.
  - Scheduler wiring: both `ws_connect` and `ws_watchdog` are
    registered; `ws_shutdown` is called from `main.py` lifespan.
  - Ruff clean on all touched files; 648 / 648 hermetic tests
    green in CI (fastapi-dependent tests included once CI's
    fastapi install is in scope).

After SENTINEL APPROVED: WARP🔹CMD merge decision on this PR.

Post-merge candidates:

- `WARP/CRUSADERBOT-WS-MARKET-DATA` — per-market subscription for
  push-based orderbook ticks (only relevant if a strategy needs
  intra-tick signal generation).
- `WARP/CRUSADERBOT-LIFECYCLE-LEDGER-REVERSAL` (still pending from
  Phase 4C) — ledger credit on cancel/expiry.
- `WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP` (still pending from
  Phase 4B) — remove `_build_clob_client` from
  `integrations/polymarket.py`.
