# FORGE-X Phase 10.8 — Signal Activation & Debug Report

**Date:** 2026-04-01  
**Branch:** `feature/forge/phase10-8-signal-activation`  
**Phase:** 10.8  
**Status:** ✅ Implementation Complete

---

## 1. What Was Fixed / Built

### Signal Debug Logging (`signal/signal_engine.py`)
- Every signal decision is logged with a structured `signal_decision` event containing:
  `market`, `p_model`, `p_market`, `edge`, `threshold`, `decision` (EXECUTE/SKIP), `reason`
- Every decision_callback invocation logs `decision_callback_triggered`
- All errors from the callback are logged with full context and re-raised cleanly

### Signal Counter Metrics (`monitoring/signal_metrics.py`)
- `SignalMetrics` class tracks:
  - `total_signals_generated` — signals accepted for execution
  - `total_signals_skipped` — signals rejected with reason breakdown
  - Reason breakdown: `low_edge`, `low_liquidity`, `risk_block`, `duplicate`
- `SignalMetricsSnapshot.to_dict()` provides JSON-serialisable output for reports and logs
- Integrated into health log and `build_report()`

### Signal Debug Mode (`SIGNAL_DEBUG_MODE`)
- `SignalEngine` reads `SIGNAL_DEBUG_MODE=true` env var
- When enabled, edge threshold drops to `0.02` (configurable via `SIGNAL_DEBUG_THRESHOLD`)
- Normal threshold: `0.05` (configurable via `SIGNAL_EDGE_THRESHOLD`)
- Timeout for forced test signal: `1800s` (configurable via `SIGNAL_NO_SIGNAL_TIMEOUT_S`)

### Forced Test Signal (Fallback)
- If no signal fires within `no_signal_timeout_s` (30 min default):
  - A small safe `$1.00 USD` test signal is emitted automatically
  - Marked with `is_debug_signal=True` and `debug_id` UUID
  - Logs `signal_engine_forced_test_signal` with CRITICAL visibility

### Activity Monitor (`monitoring/activity_monitor.py`)
- Background asyncio task monitoring signal and order counts
- After 1 hour of inactivity:
  - Signals == 0 → `activity_monitor_no_signal_activity` CRITICAL log + Telegram alert
  - Orders == 0 → `activity_monitor_no_trade_activity` CRITICAL log + Telegram alert
- Rate-limited to one alert per `alert_window_s` to prevent flooding
- Runs as `lp_activity_monitor` background task in `LivePaperRunner.run()`

### Telegram Alerts (`telegram/message_formatter.py`)
- Added `format_no_signal_alert()` — "⚠️ NO SIGNAL ACTIVITY"
- Added `format_no_trade_alert()` — "⚠️ NO TRADE ACTIVITY"
- Both follow existing Telegram formatting conventions

### Execution Path Logging (`phase10/live_paper_runner.py`)
- `live_paper_runner_execution_attempt` logged before every simulated order with:
  `market_id`, `side`, `price`, `size_usd`, `is_debug_signal`
- Guard rejections now also record `signal_metrics.record_skip(reason)` with proper
  reason classification (`duplicate` vs `risk_block`)
- `build_report()` updated to `phase: "10.8"` and includes `signal_metrics` section

---

## 2. Signal Flow Validation

```
WS Event
  └─► _handle_orderbook_event()
        ├─ decision_callback_triggered  [DEBUG log]
        └─► SignalEngine.__call__(market_id, ctx)
              ├─ check forced test signal timeout (30m)
              ├─► wrapped_callback(market_id, ctx) → raw_signal | None
              ├─ edge = |p_model - p_market|
              ├─ if edge < threshold → signal_decision(SKIP, low_edge)
              └─ if edge ≥ threshold → signal_decision(EXECUTE)
                    └─► _simulate_order()
                          ├─ live_paper_runner_execution_attempt  [INFO log]
                          ├─ RiskGuard check
                          ├─ ExecutionGuard.validate()
                          │    └─ on reject → signal_metrics.record_skip(reason)
                          └─► ExecutionSimulator.execute()
                                └─► FillTracker + MetricsValidator
```

---

## 3. Logs Summary

| Event | Level | When |
|-------|-------|------|
| `decision_callback_triggered` | DEBUG | Every orderbook tick with callback |
| `signal_decision` | INFO | Every tick (EXECUTE or SKIP) |
| `signal_engine_forced_test_signal` | WARNING | After 30m silence |
| `live_paper_runner_execution_attempt` | INFO | Before every simulated order |
| `live_paper_runner_guard_rejected` | DEBUG | ExecutionGuard block |
| `live_paper_runner_health` | INFO | Every 60s (includes signal counters) |
| `activity_monitor_no_signal_activity` | CRITICAL | After 1h no signals |
| `activity_monitor_no_trade_activity` | CRITICAL | After 1h no orders |
| `signal_metrics_summary` | INFO | On-demand via `log_summary()` |

---

## 4. Whether Signals Generated

Signals will now generate under the following conditions:

1. **Normal operation**: `decision_callback` returns a signal with `|p_model - p_market| ≥ edge_threshold`
2. **Debug mode** (`SIGNAL_DEBUG_MODE=true`): threshold lowered to `0.02` — more signals observed
3. **Forced fallback**: After 30 minutes of silence, one `$1.00` test signal is auto-generated

**Minimum viable signal requires:**
- `size_usd > 0` and `price > 0`
- RiskGuard not disabled
- ExecutionGuard validation pass (liquidity, slippage, dedup)

---

## 5. Whether Trades Executed

All signals flow through `ExecutionSimulator` (PAPER mode, `send_real_orders=False`).

For a trade to execute:
- Signal must pass `_simulate_order()` validation chain
- `ExecutionSimulator.execute()` must return `success=True`
- Fill is recorded in `FillTracker` and `MetricsValidator`

The forced test signal guarantees at least 1 order attempt per 30-minute silence window.

---

## 6. Root Cause (If Still No Trades)

If trades still do not execute after Phase 10.8:

1. **No decision_callback wired**: Runner built without `decision_callback` → no signals possible
   - Fix: Pass a valid async callback to `LivePaperRunner()` or `from_config()`

2. **Edge threshold too high**: All model predictions within market spread
   - Fix: Set `SIGNAL_DEBUG_MODE=true` or lower `SIGNAL_EDGE_THRESHOLD`

3. **Liquidity guard blocking**: `ExecutionGuard` rejects due to depth < minimum
   - Fix: Check `live_paper_runner_guard_rejected` logs for `reason`

4. **Kill switch active**: `RiskGuard.disabled=True` from prior daily loss breach
   - Fix: Check `live_paper_runner_blocked_kill_switch` logs; reset risk state

5. **WS feed not delivering orderbook**: No `snap.is_valid` → callback never invoked
   - Fix: Verify WS connection; check `live_paper_runner_orderbook_not_ready` logs

---

## 7. Next Step — Phase 10.9

- Add live model probability feed (real `p_model` values from prediction engine)
- Implement multi-market signal selection (best EV across all tracked markets)
- Add position sizing integration with `CapitalAllocator`
- Wire `ActivityMonitor` alert to `/prelive_check` command response
- Add signal replay / backtest mode against captured WS event log

---

## Files Created / Modified

| File | Action |
|------|--------|
| `signal/__init__.py` | Created |
| `signal/signal_engine.py` | Created |
| `monitoring/signal_metrics.py` | Created |
| `monitoring/activity_monitor.py` | Created |
| `telegram/message_formatter.py` | Modified — added `format_no_signal_alert`, `format_no_trade_alert` |
| `phase10/live_paper_runner.py` | Modified — integrated SignalEngine, ActivityMonitor, execution logging |
| `report/FORGE-X_PHASE10.8.md` | Created (this file) |
| `tests/test_phase108_signal_activation.py` | Created |
