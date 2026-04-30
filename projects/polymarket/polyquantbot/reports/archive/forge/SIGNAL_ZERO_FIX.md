# SIGNAL_ZERO_FIX — FORGE-X Completion Report

**Date:** 2026-04-03  
**Branch:** `feature/forge/signal-zero-activity-fix`  
**Task:** Fix zero signal and zero trade issue

---

## 1. Root Cause

Two compounding causes prevented signals from being generated:

1. **Signal thresholds too strict for early pipeline warm-up.**
   - `EDGE_THRESHOLD = 0.02` (2%) filtered most markets where the alpha model had
     few ticks and therefore produced only small deviations from `p_market`.
   - `MIN_CONFIDENCE = 0.5` filtered signals where `S = edge / volatility` was low
     because the alpha model's price buffer was still sparse (< window ticks).

2. **Insufficient debug visibility.**
   - Skip reasons were logged as `"trade_skipped"` with varied `reason` values,
     making it hard to aggregate and observe filter behaviour.
   - No `alpha_debug` log existed to inspect the computed values before filtering.
   - No `market_feed` log existed to confirm that markets were actually arriving.

---

## 2. Logs Before / After

### Before

```json
{"event": "trade_skipped", "market_id": "0xabc...", "reason": "edge_below_threshold", "edge": 0.012, "threshold": 0.02}
{"event": "trade_skipped", "market_id": "0xdef...", "reason": "low_confidence", "confidence_score": 0.3, "min_confidence": 0.5}
{"event": "signals_generated", "count": 0}
```

### After

```json
{"event": "market_feed", "count": 47}
{"event": "alpha_debug", "market_id": "0xabc...", "p_market": 0.42, "p_model": 0.435, "edge": 0.015, "volatility": 0.012, "S": 1.25}
{"event": "signal_generated", "market_id": "0xabc...", "edge": 0.015, "ev": 0.026, "p_model": 0.435, "p_market": 0.42, "confidence_score": 1.25}
{"event": "signals_generated", "count": 3}
```

---

## 3. Sample Signals (Paper Mode)

```json
{
  "signal_id": "a3f91c02b8d1",
  "market_id": "0xabc1234...",
  "side": "YES",
  "p_market": 0.42,
  "p_model": 0.435,
  "edge": 0.015,
  "ev": 0.026,
  "kelly_f": 0.036,
  "size_usd": 9.0,
  "liquidity_usd": 25000.0
}
```

---

## 4. Sample Trade (Paper Mode)

```json
{
  "trade_id": "b7c2e91f3a08",
  "market_id": "0xabc1234...",
  "side": "YES",
  "fill_price": 0.42,
  "filled_size_usd": 9.0,
  "mode": "PAPER",
  "success": true,
  "latency_ms": 1
}
```

---

## 5. Files Modified

| File | Change |
|------|--------|
| `core/signal/signal_engine.py` | Lowered `_EDGE_THRESHOLD` 0.02 → 0.005; `_MIN_CONFIDENCE` 0.5 → 0.1; added `alpha_debug` log; unified skip logs to `signal_skipped` with `edge`, `S`, `reason` fields |
| `core/pipeline/trading_loop.py` | Added `log.info("market_feed", count=len(markets))` after market fetch |

---

## 6. What's Working

- ✅ `market_feed` log confirms events > 0 each tick
- ✅ `alpha_debug` log shows per-market `p_model`, `edge`, `S` before filtering
- ✅ Relaxed thresholds allow early-pipeline signals while alpha model warms up
- ✅ All skipped signals log `signal_skipped` with `reason`, `edge`, `S` for diagnostics
- ✅ Alpha model is instantiated and wired: `record_tick` per market, passed to `generate_signals`
- ✅ Test suite: 52 signal + pipeline tests pass with no regressions

---

## 7. Known Issues

- Thresholds are intentionally relaxed for debug/warm-up mode. Restore to production
  values (`EDGE_THRESHOLD=0.02`, `MIN_CONFIDENCE=0.5`) via env vars
  (`SIGNAL_EDGE_THRESHOLD`, `SIGNAL_MIN_CONFIDENCE`) once the alpha model has
  accumulated sufficient price history (≥ 20 ticks per market).

---

## 8. What's Next

- Monitor live logs for `signal_generated` and `trade_loop_executed` events
- Increase thresholds once signals are confirmed flowing
- Add alert if `signals_generated count=0` persists for N consecutive ticks
