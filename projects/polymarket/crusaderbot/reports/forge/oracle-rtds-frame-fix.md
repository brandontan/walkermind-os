# WARP•R00T Bugfix — oracle-rtds-frame-fix (WARP-66 unblock)

Role: WARP•R00T
Branch: WARP/ROOT/oracle-rtds-frame-fix
Linear: WARP-66 blocker · Parent epic: WARP-61 (multi-asset candle oracle, Chunks 1-3 merged @ a92fec2)
Date: 2026-06-04 12:25 Asia/Jakarta
Validation Tier: MAJOR (oracle is on the strategy/intelligence path; advisory-only this lane)
Claim Level: NARROW INTEGRATION (real client driven over the live wire through the wired advisory path)
Validation Target: RTDS subscribe/parse wire-format correctness + multi-asset price_to_beat capture, end to a `computed` advisory edge per asset.
Not in Scope: `would_pass` hard-gating, risk/execution/`ENABLE_LIVE_TRADING`, Kelly, flag defaults, Fly deploy. None touched.

---

## Problem found

The candle oracle produced a None-storm in paper: **0 ticks, 100% `warming_up`**, so
`_observe_oracle_edge` never reached `computed` and WARP-66 was blocked. Diagnosis
pointed at `_build_subscribe_frame`; live verification confirmed it AND surfaced a
second, independent defect that would have left SOL permanently dead even after the
subscribe fix.

## Root cause

**RC1 — wrong feed + wrong frame shape (`domain/strategy/oracle/rtds.py`).**
`_build_subscribe_frame` subscribed to topic `crypto_prices` (the **Binance** source)
with `type: "update"` and a top-level per-symbol field. The Polymarket crypto up/down
candle markets resolve on **Chainlink**, served on a different topic, and the server
rejects the per-symbol top-level shape — so no ticks ever arrived.

Verified live against `wss://ws-live-data.polymarket.com` (raw-frame dump, 2026-06-04):

```
SUBSCRIBE: {"action":"subscribe","subscriptions":[
  {"topic":"crypto_prices_chainlink","type":"*","filters":""}]}

TICK:      {"topic":"crypto_prices_chainlink","type":"update",
            "connection_id":"...","timestamp":<ms>,
            "payload":{"symbol":"btc/usd","value":64091.353068108285,
                       "full_accuracy_value":"64091...000","timestamp":<ms>}}
```

- topic is `crypto_prices_chainlink`; subscribe `type:"*"` (ticks echo `type:"update"`).
- `filters` MUST be a **string**. `""` subscribes to every symbol. A filters *object*
  (`{"symbol":"btc/usd"}`) is rejected: `{"message":"Invalid request body"}`. So the
  correct posture is broadcast-subscribe + scope client-side — which preserves the
  BTC/ETH/SOL symbol-map abstraction (`_symbol_set` already filters in `_parse_tick`).
- price is `payload.value` (USD float). `full_accuracy_value` is the same number as a
  1e18-scaled integer string; `_parse_tick` already read `value` first and unwrapped
  the nested `payload`, so the parser was correct — only the subscribe frame was wrong.

**RC2 — BTC-only sanity band silently killed SOL (`domain/strategy/oracle/price_to_beat.py`).**
The candle-open "Price to Beat" passed through a single band `[$1,000, $100M]`. With the
oracle now multi-asset, every SOL reference (~$70) fell below the floor and returned
`None` → permanent `no_price_to_beat` for SOL → its edge could never compute. ETH (~$1,790)
happened to clear $1,000 today, but the band was conceptually BTC-scaled and fragile.

## Risk level

HIGH (functional blocker, advisory path). No capital-path or safety risk: the lane is
flag-OFF by default and advisory-only; nothing here can place, resize, or block a trade.

## Technical impact

- Oracle now receives live Chainlink ticks for all configured symbols (BTC/ETH/SOL +
  whatever else the broadcast carries, filtered to the configured set).
- `price_to_beat` is asset-aware, so SOL (and any sub-$1k asset) captures a baseline.
- The wired advisory path reaches `computed` per asset with correct per-asset values.

## Recommended solution (implemented)

1. `_build_subscribe_frame` → single broadcast Chainlink subscription
   `{topic: crypto_prices_chainlink, type: "*", filters: ""}`; client-side symbol scoping
   retained. Docstrings updated to the verified wire-format.
2. `_parse_tick` docstring updated to the confirmed shape (value-first, nested payload);
   logic unchanged (already correct). `full_accuracy_value` intentionally not re-parsed.
3. `price_to_beat` sanity band made asset-aware by slug base: btc `1k-100M`, eth `10-10M`,
   sol `0.5-1M`, permissive finite default for unmapped symbols. The `$`-required text
   guard is unchanged.

## LIVE end-to-end proof

Real `PolymarketRTDSOracle` (no stubs) opened against the live wire, then driven straight
through the wired `late_entry_v3._observe_oracle_edge` with `price_to_beat` set 0.10% below
the live oracle and `seconds_left=120`:

```
btc/usd  oracle=63860.35  ptb=63796.49  status=computed  delta=0.001001  fair_up=0.8196  edge_up=0.2696
eth/usd  oracle=1790.92   ptb=1789.13   status=computed  delta=0.001001  fair_up=0.7589  edge_up=0.2089
sol/usd  oracle=70.18     ptb=70.11     status=computed  delta=0.001001  fair_up=0.6761  edge_up=0.1261
```

All three `computed` (was 100% `warming_up`; SOL was additionally `no_price_to_beat`). Same
delta yields fair_up BTC > ETH > SOL — the per-asset sigma (SOL most volatile → least
confident) flows through correctly.

Note on Step 4 (Fly paper-deploy + `positions.strategy_metadata` query): the Fly app and the
production DB are not reachable from this container. The live-wire-through-the-wired-path run
above exercises the exact production code path (`PolymarketRTDSOracle.get_price` →
`_observe_oracle_edge` → `oracle_edge_status`) on real frames, which is a stronger correctness
signal than a black-box DB read. Recommended operator follow-up: set `ORACLE_ENABLED=true` +
`ORACLE_EDGE_GATE_ENABLED=true` in Fly (PAPER) and confirm `oracle_edge_status: "computed"`
in `positions.strategy_metadata` after 3-5 min.

## Files affected

- `projects/polymarket/crusaderbot/domain/strategy/oracle/rtds.py` (subscribe frame + docstrings)
- `projects/polymarket/crusaderbot/domain/strategy/oracle/price_to_beat.py` (asset-aware band)
- `projects/polymarket/crusaderbot/tests/test_oracle_rtds.py` (3 new tests + updated frame/band assertions)

## Validation performed

- Live raw-frame dump confirming topic/type/filters/field-names/symbol-casing (2 probes:
  broadcast frame works; filters-object rejected).
- Live end-to-end run: `computed` advisory edge for BTC/ETH/SOL with valid delta + fair_up.
- 60/60 oracle tests pass (`test_oracle_rtds.py` + `test_oracle_fair_value.py` +
  `test_oracle_edge_wiring.py`), including 3 new regression tests (verified subscribe frame,
  off-map symbol drop, asset-aware SOL/ETH band).
- 2508 full-suite tests pass; ruff clean on changed files. The 6 failures + 10 collection
  errors in the suite are pre-existing, in unrelated modules (webtrader auth/bcrypt,
  account-link, paper-signup, playbook roster), caused by missing optional deps in this
  container — none import the oracle layer.

## What is next

- WARP🔹CMD: merge → unblocks WARP-66.
- Operator (optional): flip the two flags in Fly PAPER to collect advisory telemetry.
- The live RTDS frame is now verified, satisfying that SENTINEL carry-forward precondition;
  the future hard-gate follow-up still needs flip_hunter momentum history + a fresh
  WARP•SENTINEL run (it is the real capital-path change), and is NOT in this lane.
