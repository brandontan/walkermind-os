# WARP•R00T FORGE REPORT — clob-tick-size

Branch: WARP/ROOT/clob-tick-size
Date: 2026-05-30 05:30 Asia/Jakarta
Role: WARP•R00T

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : CLOB order correctness — tick_size + neg_risk wired into all three post_order call sites
Not in Scope      : paper trading behavior, risk gate, strategy logic, live trading activation

## 1. What was built

Three surgical fixes to wire real CLOB market parameters into every live order submission path.

**Root cause**: `live.py` (BUY entry + SELL close) and `lifecycle.py` (slippage retry) called
`client.post_order()` without `tick_size` or `neg_risk`. The helpers `get_tick_size` and
`get_neg_risk` existed on `MarketDataClient` but had zero callers. Result: for live orders
(LIVE-gated — no paper impact), the CLOB received non-tick-aligned prices and orders signed
against the wrong Exchange contract for neg_risk markets → CLOB rejection.

**Fix A — `live.execute()` BUY entry (live.py)**
After `token_id` is resolved, fetches `tick_size` (e.g. "0.001" or "0.01") and `neg_risk`
(bool) from `MarketDataClient`. Passes `tick_size` to `compute_aggressive_limit_price` so the
price offset uses the real tick quantum. Passes both to `post_order`. Graceful degradation on
fetch failure: logs WARNING and falls back to defaults `("0.01", False)` — same behavior as
before this fix for the failure case.

**Fix B — `live.close_position()` SELL close (live.py)**
Same fetch pattern after `token_id` resolution. Both values forwarded to `post_order`.

**Fix C — `lifecycle._on_slippage_retry()` slippage retry (lifecycle.py)**
Restructured: DB market lookup and `token_id` resolution moved BEFORE the tick-based price
widening calculation (was after). Fetches `tick_size` + `neg_risk` after `token_id` is known.
Replaces hardcoded `tick_size = 0.01` with `float(_tick_size)` for price widening. Forwards
both to `post_order`.

## 2. Current system architecture

CLOB order path (unchanged structure):
```text
signal → risk gate → execute() → MarketDataClient.get_tick_size/get_neg_risk → post_order
                    close_position() → MarketDataClient → post_order
                    _on_slippage_retry() → MarketDataClient → post_order
```

`MarketDataClient` is an unauthenticated HTTP client for read-only CLOB market data. It is
instantiated as an async context manager (`async with MarketDataClient() as mdc`). The three
call sites now each create their own scoped context per invocation — no shared state, no race.

## 3. Files created / modified

Modified: projects/polymarket/crusaderbot/domain/execution/live.py
  - Added `MarketDataClient` to imports from `...integrations.clob`
  - `execute()`: added `_tick_size`/`_neg_risk` fetch block after token_id resolution;
    `compute_aggressive_limit_price` now receives `tick_size=float(_tick_size)`; `post_order`
    gains `tick_size=_tick_size, neg_risk=_neg_risk`
  - `close_position()`: added same fetch block after token_id resolution; `post_order` gains
    `tick_size=_tick_size, neg_risk=_neg_risk`

Modified: projects/polymarket/crusaderbot/domain/execution/lifecycle.py
  - Added `MarketDataClient` to imports from `...integrations.clob`
  - `_on_slippage_retry()`: moved DB market lookup + token_id resolution before price
    widening; added `_tick_size`/`_neg_risk` fetch block; replaced `tick_size = 0.01` with
    `tick_size_f = float(_tick_size)` for price widening; `post_order` gains
    `tick_size=_tick_size, neg_risk=_neg_risk`

Created: projects/polymarket/crusaderbot/tests/test_clob_tick_size.py
  - 8 hermetic tests across 3 test classes:
    * TestExecuteTickSize (3): tick_size+neg_risk forwarded to post_order; graceful fallback
      on MDC failure; non-default tick_size (0.001) produces correct price 0.601 vs old 0.61
    * TestClosePositionTickSize (2): same for SELL close path
    * TestSlippageRetryTickSize (3): tick_size+neg_risk forwarded; price widen uses fetched
      tick_size (0.001 → price 0.601, not 0.61); defaults on MDC failure

## 4. What is working

- py_compile clean on both modified files
- 8/8 new tests pass
- 77/77 existing live execution regression tests pass (test_live_execution_rewire,
  test_live_gate_hardening, test_live_path_hardening)
- Graceful degradation: fetch failure logs WARNING and uses defaults — no behavior change
  relative to the pre-fix state for the error path
- All three call sites now pass correct CLOB market parameters on the happy path

## 5. Known issues

None introduced.

## 6. What is next

- Consecutive empty candle-universe operator Telegram alert (follow-up from candle-sync incident):
  alert after N consecutive ticks where `get_crypto_window_markets` returns empty during
  market hours.
- `MAX_CONCURRENT_TRADES=5` dead constant vs per-profile cap (up to 20) — WARP🔹CMD policy call.
- Legacy `_build_clob_client` footgun in `integrations/polymarket.py:479-561` — dead code;
  pending importer verification before delete.
- `get_usdc_balance` unit heuristic (`adapter.py` `>1e6` guess) — pending live API shape
  confirmation before fix.
- WARP🔹CMD review + merge. WARP•R00T self-validates this MAJOR lane (per WARP🔹CMD delegation).
