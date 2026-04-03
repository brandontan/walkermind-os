# FORGE-X — Signal Debug + Force Signal Mode Report

**Date:** 2026-04-03  
**Branch:** feature/forge/signal-debug-force-mode  
**Status:** COMPLETE ✅

---

## 1. What Was Built

This task enables full signal visibility and force signal generation to validate the
end-to-end trading pipeline (alpha → signal → execution → pnl).

### Parts delivered:

| Part | Description | Status |
|------|-------------|--------|
| 1 | Signal debug log enrichment (`S` field added) | ✅ |
| 2 | `FORCE_SIGNAL_MODE` env flag + bypass logic | ✅ |
| 3 | Risk limits in force mode (1 % bankroll, max 1 trade/loop) | ✅ |
| 4 | Execution trace logs (`order_sent`, `order_filled`) | ✅ |
| 5 | Tests (FS-01 – FS-10) | ✅ |

---

## 2. System Architecture (affected modules)

```
DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING
                       ↑                    ↑
              signal_engine.py         executor.py
              trading_loop.py
```

### Signal Debug Flow

```
generate_signals()
  │
  ├── for each market:
  │     log "signal_debug" {market_id, p_market, p_model, edge, volatility, S}  ← NEW: S added
  │
  ├── [NORMAL MODE] apply filters (edge, liquidity, confidence)
  │     └── log "signal_skipped" {reason}
  │
  └── [FORCE MODE] bypass all filters
        ├── pick top-N markets (FORCE_SIGNAL_TOP_N, default 1)
        ├── side = YES if p_market < 0.5 else NO
        ├── size = bankroll * 0.01
        └── log "signal_generated" {force_mode=True}
```

### Execution Trace Flow

```
_attempt_execution()
  │
  ├── log "order_sent"   {trade_id, market_id, side, price, size_usd, mode}  ← NEW
  │
  ├── [PAPER] simulate fill
  │     └── log "order_filled" {filled_size_usd, fill_price, latency_ms}      ← NEW
  │
  └── [LIVE] call executor_callback
        └── log "order_filled" {filled_size_usd, fill_price, latency_ms}      ← NEW
```

---

## 3. Files Created / Modified

| File | Change |
|------|--------|
| `core/signal/signal_engine.py` | Added `S` to `signal_debug` log; added `FORCE_SIGNAL_MODE` env support; added `_env_int`, `_env_bool` helpers; added `force_signal_mode` parameter to `generate_signals()`; added `_FORCE_SIGNAL_TOP_N` constant |
| `core/execution/executor.py` | Added `order_sent` log before execution; added `order_filled` log after fill (both paper and live paths) |
| `core/pipeline/trading_loop.py` | Added `_env_bool` helper; reads `FORCE_SIGNAL_MODE`; passes `force_signal_mode` to `generate_signals()`; enforces max 1 trade per loop when force mode is active; logs `force_signal_mode` in `trading_loop_started` and `signals_generated` events |
| `tests/test_signal_execution_activation.py` | Added 10 new tests (FS-01 – FS-10) for force signal mode and execution trace |
| `reports/forge/SIGNAL_DEBUG_FORCE_MODE.md` | This report |

---

## 4. Sample Debug Logs

### Normal mode (signal_debug with S):
```json
{
  "event": "signal_debug",
  "market_id": "0xabc123",
  "p_market": 0.42,
  "p_model": 0.61,
  "edge": 0.19,
  "volatility": 0.0001,
  "effective_threshold": 0.00505,
  "S": 1900.0
}
```

### Force mode activation:
```json
{"event": "force_signal_mode_active", "top_n": 1, "bankroll": 1000.0, "force_size_usd": 10.0}
{"event": "signal_debug", "market_id": "0xabc123", "p_market": 0.55, "p_model": 0.55, "edge": 0.0, "S": 0.0, "force_mode": true}
{"event": "signal_generated", "market_id": "0xabc123", "side": "NO", "size_usd": 10.0, "force_mode": true}
```

### Execution trace:
```json
{"event": "order_sent",   "trade_id": "trade-a1b2c3d4", "market_id": "0xabc123", "side": "YES", "price": 0.42, "size_usd": 10.0, "mode": "PAPER"}
{"event": "order_filled", "trade_id": "trade-a1b2c3d4", "market_id": "0xabc123", "filled_size_usd": 10.0, "fill_price": 0.42, "latency_ms": 0.05, "mode": "PAPER"}
```

---

## 5. Forced Signal Logic

```
ENV: FORCE_SIGNAL_MODE=true
ENV: FORCE_SIGNAL_TOP_N=1  (default)

For each of top-N markets:
  side  = "YES" if p_market < 0.5 else "NO"
  size  = bankroll * 0.01    # 1 % cap
  edge  = p_model - p_market  # may be 0 or negative in debug scenario

Trading loop guard:
  max 1 trade executed per loop tick (force_mode_max_1_trade_per_loop)
```

---

## 6. Validation Results

```
tests/test_signal_execution_activation.py
  SE-01 – SE-14  : signal engine (all pass) ✅
  EX-01 – EX-18  : executor (all pass) ✅
  FS-01 – FS-10  : force signal mode (all pass) ✅

Total: 42 tests passed
```

---

## 7. Known Issues

- Force mode signals with `edge <= 0` are still rejected by the executor's risk
  re-validation (`edge_non_positive`). This is **intentional** — the executor's
  risk layer is never bypassed even in debug mode. Use a market with positive (but
  sub-threshold) edge for a fully traced execution test.

---

## 8. What's Next

- Monitor `signal_debug` logs in production to tune `SIGNAL_EDGE_THRESHOLD`
- Verify `order_sent`/`order_filled` latency in live mode
- Disable `FORCE_SIGNAL_MODE` before going live
