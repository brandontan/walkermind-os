# WARP•FORGE Report — oracle-chainlink-client (multi-asset RTDS)

Role: WARP•R00T (operating as WARP•FORGE for this build lane)
Branch: WARP/ROOT/oracle-chainlink-client
Linear: WARP-62 (Chunk 1/4) · Parent: WARP-61 · Blocks: WARP-64 (Chunk 3)
Date: 2026-06-04 09:18 Asia/Jakarta

Validation Tier   : STANDARD
Claim Level       : FOUNDATION
Validation Target : domain/strategy/oracle/ multi-asset price stream
                    (BTC/ETH/SOL via Polymarket RTDS) + staleness handling +
                    price_to_beat capture + config knobs, in isolation (network
                    stubbed). Symbol keying, frame parsing, staleness, lifecycle,
                    flag-gating, and the price_to_beat parser.
Not in Scope      : Fair-value / per-asset-sigma edge calculator (Chunk 2),
                    strategy wiring into late_entry_v3 / signal_scan / scheduler
                    (Chunk 3, WARP-64), live trading, real network calls,
                    ORACLE_ENABLED=true runtime, background-task lifecycle wiring.
Suggested Next    : WARP🔹CMD review.

---

## 1. What was built

The foundation of the candle oracle layer: an async, **multi-asset** streaming
client that reads the live oracle price the Polymarket crypto up/down candle
markets resolve against — Chainlink Data Streams for **BTC/USD, ETH/USD,
SOL/USD** — through Polymarket's own **Real-Time Data Stream (RTDS) WebSocket**
`wss://ws-live-data.polymarket.com`. Using the exchange's own stream means the
exact number the market settles on, with **no separate Chainlink Data Streams
credentials**. Plus a pure parser that captures each market's candle-open
**"Price to Beat"**.

This is the missing crypto price reference identified in the WARP-61
knowledge-graph audit (no `crypto_price` / `chainlink` / `candle_open` node
existed anywhere in the signal path).

Scope is strictly Chunk 1: stream the live price (keyed by asset symbol) and
capture the baseline. No fair value, no per-asset sigma, no edge math, no
strategy wiring. The runtime factory is gated behind a `ORACLE_ENABLED` feature
flag that defaults **OFF**, so nothing in the running system changes until the
operator opts in.

The client is **multi-asset by construction** — one connection, many feeds,
keyed by a config-driven symbol map (`ORACLE_SYMBOLS`, default
`btc/usd,eth/usd,sol/usd`, extensible to any pair). Per the task, only BTC need
be confirmed live for now, but the abstraction accepts ETH/USD + SOL/USD via
config with zero code change — the default subscribes to all three.

Anti-fake-data posture (consistent with the prior `kill-fabricated-prices`
lane): the client **never** returns a stale or fabricated price. A symbol with
no tick, or whose newest tick is older than `ORACLE_STALENESS_SEC`, returns
`None` from `get_price` (and logs the staleness drop). `get_price_to_beat`
returns `None` rather than guessing when no baseline is present.

## 2. Current system architecture (relevant slice)

New package `projects/polymarket/crusaderbot/domain/strategy/oracle/`:

```
oracle/
├── __init__.py        public surface (PolymarketRTDSOracle, errors,
│                      oracle_from_settings, normalize_symbol, parse_symbols,
│                      get_price_to_beat)
├── rtds.py            PolymarketRTDSOracle — multi-symbol RTDS WebSocket client
│                      + staleness + settings-driven, flag-gated factory
└── price_to_beat.py   pure get_price_to_beat(market) capture
```

Streaming model (mirrors `integrations/clob/ws.py`):

```
oracle_from_settings()              # ORACLE_ENABLED gate + symbol map
  └─ PolymarketRTDSOracle
       ├─ start()                   # background _run_loop task
       ├─ _run_loop()              # reconnect w/ exponential backoff + jitter
       │    └─ _connect_and_read() # open -> subscribe -> drain frames -> close
       │         ├─ _open_connection()      # injectable connect_factory seam
       │         ├─ _build_subscribe_frame() # RTDS crypto_prices subscribe
       │         └─ _handle_message()        # _parse_tick -> per-symbol cache
       ├─ get_price(symbol) -> Optional[float]   # fresh tick or None (stale)
       ├─ is_stale(symbol) -> bool
       └─ stop()
```

- `connect_factory` is an injectable async seam: production uses
  `websockets.connect` (soft import, matching the CLOB WS client); tests inject
  a fake socket so no port is opened.
- Per-symbol cache stores `(price, monotonic_at)`; `get_price` compares tick age
  to `staleness_sec` on every read — a starved feed yields `None`, never the
  last good value.
- `_build_subscribe_frame` / `_parse_tick` isolate the assumed RTDS wire-format
  (`crypto_prices` topic; `{payload:{symbol,value}}`) so live verification or
  Chunk 3 can correct the shape without touching the abstraction. `_parse_tick`
  is defensive across field names and only accepts configured symbols with a
  strictly-positive finite price.

`get_price_to_beat(market)` is pure (no I/O): explicit numeric fields first
(`priceToBeat`/`openPrice`/`strikePrice`/…), then a sanity-banded ($1k–$100M)
USD figure parsed from `question`/`title`/`description` (the `$` sign is
required so a year/id cannot be mistaken for a price), else `None`.

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/domain/strategy/oracle/__init__.py`
- `projects/polymarket/crusaderbot/domain/strategy/oracle/rtds.py`
- `projects/polymarket/crusaderbot/domain/strategy/oracle/price_to_beat.py`
- `projects/polymarket/crusaderbot/tests/test_oracle_rtds.py`

Removed (superseded by the RTDS approach):
- `projects/polymarket/crusaderbot/domain/strategy/oracle/chainlink.py`
- `projects/polymarket/crusaderbot/tests/test_oracle_chainlink.py`

Modified:
- `projects/polymarket/crusaderbot/config.py` — oracle knobs now RTDS/multi-asset:
  `ORACLE_ENABLED`, `ORACLE_RTDS_WS_URL`, `ORACLE_SYMBOLS` (CSV symbol map),
  `ORACLE_STALENESS_SEC`. (Removed the Chainlink Data Streams URL/feed-id/creds —
  RTDS needs none.)

State files:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- `normalize_symbol` / `parse_symbols`: bare ticker, slash, and dash forms all
  canonicalise to `base/quote`; CSV map parses with order + de-dup.
- `_parse_tick` extracts `(symbol, price)` for BTC/ETH/SOL across several field
  shapes; rejects unconfigured symbols, non-numeric / NaN / inf / `<=0` prices.
- `_handle_message` contains malformed frames (no raise, cache untouched).
- `get_price` returns the fresh price, then `None` once the tick ages past
  `staleness_sec`; `is_stale` agrees. Unknown symbol → `None` / stale.
- Full lifecycle over a fake socket: `start()` → subscribe frame sent for all
  configured symbols → all three prices populated → `stop()` clean.
- Construction guards: empty url / empty symbols raise `OracleConfigError`.
- `oracle_from_settings()` raises `OracleDisabledError` when `ORACLE_ENABLED` is
  OFF (default); builds a multi-asset (BTC/ETH/SOL) oracle when enabled; honours
  a custom `ORACLE_SYMBOLS` map.
- `get_price_to_beat` field/text/None/out-of-band behaviour intact.
- 14/14 unit tests pass; `ruff check` clean; `py_compile` clean. Network fully
  stubbed.

## 5. Known issues

- The RTDS subscribe/message wire-format (`crypto_prices` topic, `{payload:
  {symbol,value}}`) is the documented-best-effort shape, isolated in
  `_build_subscribe_frame` / `_parse_tick`. It must be confirmed against a live
  `wss://ws-live-data.polymarket.com` session before enablement; the defensive
  parser tolerates several field names but the exact frame should be verified.
  Per task scope, BTC is the asset to confirm live first; ETH/SOL ride the same
  parser.
- Background-task lifecycle (where/when `start()`/`stop()` are called in the app)
  is intentionally NOT wired here — that is Chunk 3 runtime integration. The
  foundation exposes the class + flag-gated factory only.
- No live network call has been exercised (foundation, flag OFF). End-to-end
  validation against the real RTDS endpoint is deferred to operator enablement.

## 6. What is next

- Chunk 2/4: fair-value / edge calculator with **per-asset sigma** (SOL > ETH >
  BTC, never shared) — consumes `get_price(symbol)` + `get_price_to_beat()`.
  NOT started here per chunk scope.
- Chunk 3/4 (WARP-64): wire the oracle + edge gate into `late_entry_v3` presets
  (Distance / Min Edge / Trend) across BTC/ETH/SOL and 5m/15m, including the
  oracle start/stop lifecycle in the runtime. Blocked on this lane + Chunk 2.
- Operator pre-activation (later): confirm the RTDS frame shape on a live
  session, optionally tune `ORACLE_SYMBOLS` / `ORACLE_STALENESS_SEC`, then flip
  `ORACLE_ENABLED=true`.
