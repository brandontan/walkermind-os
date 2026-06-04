# WARP•R00T — oracle-price-to-beat-buffer (WARP-68)

Role: WARP•R00T
Branch: WARP/ROOT/oracle-price-to-beat-buffer
Linear: WARP-68 · Blocks: WARP-66 (hard-gate) · Follows: WARP-67 (RTDS frame fix, merged)
Date: 2026-06-04 13:05 Asia/Jakarta
Validation Tier: MAJOR (oracle/strategy intelligence path; advisory-only)
Claim Level: NARROW INTEGRATION (real client driven over the live wire through the wired path)
Validation Target: derive `price_to_beat` from the RTDS Chainlink history at the candle-open epoch, so the advisory edge reaches `computed` across BTC/ETH/SOL.
Not in Scope: `would_pass` hard-gating, risk/execution/`ENABLE_LIVE_TRADING`, Kelly, flag defaults, the flip_hunter Trend momentum history (WARP-66). None touched.

---

## Problem found

After WARP-67 the RTDS Chainlink feed is live (`oracle_now` computes), but the advisory
edge was stuck at **`no_price_to_beat`** in production for every candle — even BTC/ETH.
Polymarket candle markets carry **no** "Price to Beat" field, so the baseline could not be
captured.

## Root cause

The candle-open reference price is not in any market metadata the bot receives. Verified
against the **live Gamma payload** (recon, before building):

- No `priceToBeat` / `openPrice` / `strike` / `referencePrice` field anywhere; the only
  price-ish fields are market-trading data (`bestBid`/`bestAsk`/`lastTradePrice`/`outcomePrices`).
- The candle question is just `"Bitcoin Up or Down - June 4, 1:25AM-1:30AM ET"` — no `$` figure
  for the text parser to find. The `markets` table likewise has no such column.
- `resolutionSource` = `https://data.chain.link/streams/btc-usd` (eth-usd / sol-usd) → the
  candle resolves on **Chainlink Data Streams**, the SAME source as our RTDS feed and
  `oracle_now`. The candle open is exposed as `eventStartTime` (and the slug trailing unix ts).

So the baseline must be **derived from our own Chainlink feed at the candle open** — basis-clean
because it is the same source the market settles on.

## Recon — RTDS wire (before building, per owner directive)

- **No historical/backfill dump exists.** `crypto_prices_chainlink` accepts only `type: "update"`;
  the server's topic/type registry rejects `snapshot`/`ohlc`/`candle`/`agg`/`history`/`historical`/`init`
  and a `_historical` topic (`leger GetTopics ... NotFound`); a plain connect delivers no backfill.
  → The owner's caveat #1 ("seed from a `CryptoPriceHistorical` dump") cannot be met — there is no
  such dump. The ring fills from live ticks; the cold-start gap self-closes after ≤1 candle of uptime
  (fail-soft `no_price_to_beat` meanwhile). Zero-gap-on-restart would need the deferred
  boundary-snapshot+DB option (WARP-66-era).
- **Cadence = exactly 1 Hz**, aligned to whole seconds → a tick sits within ~1 s of any candle open,
  so a ≤2 s tolerance matches the open tick reliably; beyond it → honest `no_price_to_beat`.

## Recommended solution (implemented)

Rolling per-symbol history ring in the RTDS oracle + a `price_at(open_epoch)` lookup, wired as a
`price_to_beat` fallback in the advisory observation.

- `rtds.py`: per-symbol time-ordered ring of `(chainlink_report_ms, price)`, time-pruned to
  `ORACLE_HISTORY_WINDOW_SEC` (default 1800 s / 30 min) off the newest tick's own report time
  (clock-skew-proof) with a hard maxlen safety cap. `_parse_tick` now also returns the Chainlink
  report timestamp. `price_at(symbol, epoch_sec, tolerance_sec=2.0)` returns the price of the tick
  nearest the candle open ONLY within tolerance — never a far/stale tick (a wrong open corrupts delta).
- `late_entry_v3.py`: `_candle_open_epoch(market, slug)` (slug trailing unix ts primary,
  `eventStartTime` fallback); `_observe_oracle_edge` resolves `price_to_beat` as
  explicit-metadata → buffer-at-open → None, and stamps `oracle_price_to_beat_source`
  (`metadata` | `oracle_buffer`). `OracleEdgeConfig` gains `price_at_provider` + `ptb_tolerance_sec`.
- `signal_scan_job.py`: the lazy oracle singleton's `price_at` + `ORACLE_PTB_TOLERANCE_SEC` are
  threaded into the edge config.
- `config.py`: `ORACLE_HISTORY_WINDOW_SEC` (1800), `ORACLE_PTB_TOLERANCE_SEC` (2.0).

## Risk level

HIGH (advisory functional blocker). No capital-path/safety risk: flag-gated OFF, advisory,
fail-soft; nothing here can place, resize, or block a trade.

## Invariant honored

`price_to_beat` is the Chainlink value at candle open, same source as `oracle_now` — both from the
RTDS Chainlink feed → basis-clean delta, no spot/Chainlink basis corruption near close.

## LIVE end-to-end proof

Real `PolymarketRTDSOracle` over the live wire, buffered ~12 s, then driven through the wired
`_observe_oracle_edge` with markets carrying NO price-to-beat field:

```
btc/usd  oracle=64068.84  price_to_beat=64057.02 (source=oracle_buffer)  status=computed  delta=0.000185  fair_up=0.5669
eth/usd  oracle=1786.40   price_to_beat=1786.09  (source=oracle_buffer)  status=computed  delta=0.000172  fair_up=0.5480
sol/usd  oracle=70.36     price_to_beat=70.34    (source=oracle_buffer)  status=computed  delta=0.000355  fair_up=0.5644
```

All three reach `computed` with `price_to_beat` sourced from the buffer at the candle-open epoch
(was 100% `no_price_to_beat`).

## Files affected

- `projects/polymarket/crusaderbot/domain/strategy/oracle/rtds.py`
- `projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py`
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py`
- `projects/polymarket/crusaderbot/config.py`
- `projects/polymarket/crusaderbot/tests/test_oracle_rtds.py`
- `projects/polymarket/crusaderbot/tests/test_oracle_edge_wiring.py`

## Validation performed

- Live Gamma payload recon (no price-to-beat field; resolution = Chainlink) + RTDS wire recon
  (no dump; 1 Hz cadence).
- Live end-to-end: `computed` with buffer-sourced `price_to_beat` for BTC/ETH/SOL.
- 67 oracle tests pass (7 new: price_at within/outside tolerance, cold buffer, window pruning,
  candle-open epoch parsing, buffer-derived computed, buffer-miss no_price_to_beat,
  metadata-preferred-over-buffer). 2515 full-suite pass; ruff clean on changed files. The 6
  failures + 10 collection errors are pre-existing, unrelated (webtrader/account/roster, missing
  optional deps) — none import the oracle layer.

## What is next

- WARP🔹CMD: merge → Fly CD redeploy → confirm `oracle_edge_status: "computed"` (with
  `oracle_price_to_beat_source: "oracle_buffer"`) across BTC/ETH/SOL in `positions.strategy_metadata`
  after ≤15 min of uptime (the ring needs to have been filling since before a candle's open).
- This unblocks WARP-66 (hard-gate): once enough `computed` candles accrue across assets, the
  go/no-go for flipping `would_pass` into a pre-EXECUTION reject can be made (still requires the
  flip_hunter Trend momentum history + a fresh WARP•SENTINEL run — that is the capital-path change).
