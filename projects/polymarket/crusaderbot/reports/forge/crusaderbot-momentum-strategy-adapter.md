# WARP•FORGE Report — crusaderbot-momentum-strategy-adapter

**Branch:** WARP/crusaderbot-momentum-strategy-adapter
**Date:** 2026-05-11
**Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** MomentumReversalStrategy adapter — scan contract, registry bootstrap, filter logic
**Not in Scope:** execution engine, risk constants, live gate, activation guards, DB schema, CLOB, capital controls

---

## 1. What Was Built

Ported the contrarian momentum idea from `lib/strategies/momentum.py` (legacy) into a CrusaderBot-native active strategy adapter. The legacy file was used as a design reference only — it is not imported at runtime.

New concrete class `MomentumReversalStrategy` (strategy name: `momentum_reversal`) implements the `BaseStrategy` contract and is registered by `bootstrap_default_strategies()` alongside `copy_trade` and `signal_following`.

Strategy behavior:
- Fetches active markets from Gamma API via `integrations.polymarket.get_markets()`.
- Filters by: `active=True`, `closed=False`, `acceptingOrders=True`, 24h price drop ≥ 10%, YES price in [0.10, 0.85], liquidity ≥ `MarketFilters.min_liquidity`, 24h volume ≥ $1,000.
- Blacklisted market IDs from `MarketFilters.blacklisted_market_ids` are excluded.
- Emits YES-side `SignalCandidate` entries only.
- Confidence = `min(abs(drop) / 0.20, 1.0)` — normalized to 20% drop ceiling.
- Sorts by confidence descending (highest drop first).
- Suggested size: 5% of allocated capital, bounded [$1, $50].
- `evaluate_exit` returns hold — platform TP/SL handles exit.
- `default_tp_sl` returns (0.15, 0.08) — conservative defaults.
- All failures caught and logged; `scan()` returns `[]` on any exception.

Risk profile compatibility: `balanced`, `aggressive` (not conservative — directional risk is inappropriate).

---

## 2. Current System Architecture

```
DATA -> STRATEGY -> INTELLIGENCE -> RISK -> EXECUTION -> MONITORING

MomentumReversalStrategy sits in the STRATEGY layer only:
  scan() -> SignalCandidate[] -> downstream risk gate (unchanged)
  evaluate_exit() -> ExitDecision(hold) -> platform TP/SL watcher (unchanged)

Registry: StrategyRegistry.bootstrap_default_strategies()
  copy_trade       (existing)
  momentum_reversal (NEW)
  signal_following  (existing)
```

No execution, risk, activation guard, CLOB, or DB schema changes.

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/domain/strategy/strategies/momentum_reversal.py`
- `projects/polymarket/crusaderbot/tests/test_momentum_reversal.py`

**Modified:**
- `projects/polymarket/crusaderbot/domain/strategy/strategies/__init__.py` — added `MomentumReversalStrategy` import and `__all__` entry
- `projects/polymarket/crusaderbot/domain/strategy/registry.py` — added `MomentumReversalStrategy` to `bootstrap_default_strategies()` loop

**Not modified (confirmed):**
- `config.py`, `risk/`, `execution/`, `activation/`, DB migrations, CLOB adapters

---

## 4. What Is Working

- `py_compile` passes for all 4 touched Python files.
- 50 hermetic tests green: BaseStrategy contract, registry bootstrap idempotency, all filter paths (status, blacklist, drop, liquidity, volume, YES price range), confidence sorting, helper extraction, evaluate_exit hold, default_tp_sl values.
- Strategy appears in active registry list alongside `copy_trade` and `signal_following` via `bootstrap_default_strategies()`.
- `MarketFilters.min_liquidity` is respected — strategy does not override or undercut the user-level filter.
- All exceptions caught; `scan()` returns `[]` rather than raising on network/API failures.
- No activation guard values changed. No live trading enablement. No CLOB changes.

---

## 5. Known Issues

- `oneDayPriceChange` field availability depends on Gamma API version. The extractor handles both `oneDayPriceChange` (top-level) and `priceChange.oneDay` (nested legacy form) with graceful fallback to `None` (market skipped) if neither is present.
- `suggested_size_usdc` is a hint only — downstream risk gate enforces the actual position-size cap. Users with very small balances may see `suggested_size_usdc = $1.0` (minimum floor).
- `evaluate_exit` is a stub (always hold). If a strategy-driven exit criterion is needed in the future (e.g., price recovered to target), it can be added without changing the contract.

---

## 6. What Is Next

- WARP🔹CMD review. Tier: STANDARD — no SENTINEL required unless scope expands into live gate, risk, or capital controls.
- If approved, paper-mode scan loop will include `momentum_reversal` candidates routed through existing risk + paper execution pipeline.
- Future enhancement (deferred): wire `evaluate_exit` to a price-target check if strategy-level exit timing is desired.

---

**Suggested Next Step:**
WARP🔹CMD review required.
Source: `projects/polymarket/crusaderbot/reports/forge/crusaderbot-momentum-strategy-adapter.md`
Tier: STANDARD
