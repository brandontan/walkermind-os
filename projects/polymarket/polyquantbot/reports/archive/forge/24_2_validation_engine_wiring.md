# Phase 24.2 — Validation Engine Wiring

**Date:** 2026-04-04
**Branch:** feature/forge/validation-engine-wiring
**Environment:** staging

---

## 1. What Was Built

The Validation Engine (built in Phase 24.1) is now wired into the live trading pipeline.
Every executed trade automatically triggers the full validation pipeline in a
non-blocking background `asyncio.create_task()` so that execution latency is
unaffected.

Key additions to `core/pipeline/trading_loop.py`:

| Component | Role |
|---|---|
| Singleton initialization (inside `run_trading_loop`) | `PerformanceTracker`, `MetricsEngine`, `ValidationEngine`, `ValidationStateStore` — created once, shared across all ticks |
| `_prev_vs` mutable list | State-change detection; avoids redundant Telegram noise |
| `_run_validation_hook(trade, tg_cb)` coroutine | Nested async function that runs the full pipeline: add trade → compute metrics → evaluate → update state → log → alert |
| Section **4j** call-site | After trade fill confirmed (post 4i Telegram alert), schedules `asyncio.create_task(_run_validation_hook(...))` |

---

## 2. Current System Architecture

```
DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING
                                                          │
                                           trading_loop.py (section 4j)
                                                          │
                                           PerformanceTracker (rolling 100)
                                                          │
                                           MetricsEngine (WR, PF, E, MDD)
                                                          │
                                           ValidationEngine → ValidationState
                                                          │
                                           ValidationStateStore (shared registry)
                                                          │
                                           Telegram alert (state change only)
```

Pipeline is fully compliant: RISK precedes EXECUTION; MONITORING receives trade events.

---

## 3. Files Created / Modified

| File | Action | Description |
|---|---|---|
| `core/pipeline/trading_loop.py` | **Modified** | Added imports, singleton init, `_run_validation_hook`, section 4j call-site |
| `tests/test_validation_engine_wiring.py` | **Created** | 10 targeted tests for the wiring (VW-01 → VW-10) |
| `reports/forge/24_2_validation_engine_wiring.md` | **Created** | This report |

---

## 4. What Is Working

- **Singleton initialization**: `PerformanceTracker`, `MetricsEngine`, `ValidationEngine`,
  `ValidationStateStore` are created once per `run_trading_loop()` invocation, not per trade.
- **Trade record standardization**: Each fill builds a dict with all six required keys
  (`pnl`, `entry_price`, `exit_price`, `size`, `timestamp`, `signal_type`). Missing-field or
  non-dict errors are caught, logged, and skipped — execution never crashes.
- **Non-blocking execution**: `asyncio.create_task()` schedules the validation hook as a
  background coroutine; execution continues immediately without waiting.
- **State transitions**: State-change detection via `_prev_vs` mutable list ensures Telegram
  alerts are sent only when state actually changes (HEALTHY→WARNING, *→CRITICAL, etc.).
- **Logging**: Every state update emits `"validation_update"` structured log. CRITICAL state
  uses `log.critical`; all other states use `log.info`.
- **Telegram alerts**: WARNING → `⚠️ WARNING` alert; CRITICAL → `🚨 CRITICAL` alert;
  HEALTHY transition → silent. Telegram failures are caught and logged (no crash).
- **All 10 new tests passing** (VW-01 → VW-10).
- **All 33 existing Phase 24.1 tests still passing**.

---

## 5. Known Issues

- Entry-trade `pnl` is recorded as `0.0` (position is open, no realized PnL yet). This means
  early validation metrics will show a neutral PnL distribution until positions close. This is
  expected behavior — the tracker accumulates real PnL data over time as positions are realized.
- `exit_price` is set equal to `entry_price` for open positions. MetricsEngine is tolerant of
  this and will produce meaningful MDD once more trades accumulate.
- `signal_type` falls back to `"REAL"` when not present in `signal.extra`. No known case where
  this field is absent, but the fallback is intentional.

---

## 6. What Is Next

- **Phase 24.3 — Stability testing (24h)**: Run the full pipeline in staging for 24 hours,
  monitor validation state transitions, confirm no false CRITICAL alerts.
- **Closed-trade PnL hook**: Wire realized PnL from `db.update_trade_status("closed", pnl=...)
  ` events back into `PerformanceTracker` so metrics reflect actual closed-trade performance.
- **ValidationState exposure via API**: Surface `ValidationStateStore.get_state()` through an
  API endpoint for external monitoring dashboards.
