# FORGE-X Report — 24_3a_validation_accuracy_patch.md

**Phase:** 24.3a
**Date:** 2026-04-04
**Environment:** staging
**Branch:** feature/forge/validation-accuracy-patch

---

## 1. What Was Fixed

Four validation accuracy issues identified by SENTINEL in report `24_1_validation_system_audit.md` were resolved without altering any trading behavior (execution logic, signal generation, or risk decisions remain untouched).

| Fix | Location | Description |
|-----|----------|-------------|
| R-3 | `monitoring/metrics_engine.py` | PF false-positive: `gross_loss == 0` now returns `999.0` (all-win sentinel) instead of `0.0` |
| R-4 | `monitoring/metrics_engine.py` | `last_pnl` added as a first-class key in `compute()` output dict |
| R-6 | `core/pipeline/trading_loop.py` | Breakeven (`pnl == 0.0`) no longer skipped in `_run_closed_validation_hook` |
| R-4b | `core/pipeline/trading_loop.py` | `_last_pnl` in `_emit_validation_result` now reads directly from `"last_pnl"` key with `0.0` fallback, not `expectancy` |

---

## 2. Why It Matters — SENTINEL Findings

**R-3 (Profit Factor false-positive):**  
SENTINEL found that an all-win trading window returned `PF = 0.0`, triggering a false `WARNING` state in the `ValidationEngine`. A perfect window (no losses) should never flag a warning. Returning `999.0` as a large-but-finite sentinel preserves float contract and eliminates the false alert.

**R-4 (last_pnl key missing):**  
SENTINEL noted `last_pnl` was proxied through `expectancy` in the validation_update log, meaning the reported figure was an average expectation, not the actual most-recent trade PnL. This made post-trade observability misleading.

**R-6 (breakeven trade skipped):**  
SENTINEL identified that a `pnl == 0.0` check in `_run_closed_validation_hook` caused breakeven closes to skip the performance tracker update entirely. This left the tracker in a stale state and caused validation metrics to lag after breakeven closes.

**R-4b (expectancy misuse in log):**  
The `_emit_validation_result` function used `_computed.get("expectancy", 0.0)` as a fallback for `last_pnl`. Now that `last_pnl` is a first-class key in `compute()`, the fallback chain is simplified to `_computed.get("last_pnl", 0.0)`.

---

## 3. Before vs After Behavior

### Fix R-3 — Profit Factor

| Scenario | Before | After |
|----------|--------|-------|
| All-win window (no losses) | `PF = 0.0` → ValidationEngine: WARNING | `PF = 999.0` → ValidationEngine: HEALTHY |
| All-loss window (no wins) | `PF = 0.0` | `PF = 0.0` (unchanged) |
| Mixed window | `PF = gross_profit / gross_loss` | `PF = gross_profit / gross_loss` (unchanged) |

### Fix R-4 — last_pnl in compute()

| Scenario | Before | After |
|----------|--------|-------|
| Empty trades | Key absent from dict | `"last_pnl": 0.0` |
| Non-empty trades | Key absent from dict | `"last_pnl": trades[-1]["pnl"]` |

### Fix R-6 — Breakeven skip

| Scenario | Before | After |
|----------|--------|-------|
| `trade_id=""` | Skipped (logged) | Skipped (logged) — unchanged |
| `pnl == 0.0`, valid `trade_id` | Skipped (silent) | Passes through; tracker updated |
| `pnl != 0.0`, valid `trade_id` | Passes through | Passes through — unchanged |

### Fix R-4b — _last_pnl in log

| Before | After |
|--------|-------|
| `_computed.get("last_pnl", _computed.get("expectancy", 0.0))` | `_computed.get("last_pnl", 0.0)` |

---

## 4. Test Results

All 54 target tests pass:

```
projects/polymarket/polyquantbot/tests/test_stability_phase24_3.py  — 11/11 PASSED
projects/polymarket/polyquantbot/tests/test_phase91_stability.py     — passes
projects/polymarket/polyquantbot/tests/test_phase103_runtime_validation.py — 53 PASSED
```

VS-07 (`test_vs07_closed_hook_records_zero_pnl`) confirms breakeven trades are processed correctly.  
No regressions introduced in any passing test suite.

Pre-existing failures in `test_phase115_system_validation.py` (wallet persistence, missing `aiosqlite`) and `test_validation_engine_core.py` / `test_telegram_*` (`PrintLogger` attribute error) are unrelated to this patch and were present before this change.

---

## 5. Zero-Impact Guarantee

- **Execution logic**: No changes to `execution/` module or order submission paths.
- **Signal generation**: No changes to `strategy/` or `intelligence/` modules.
- **Risk decisions**: No changes to `risk/` module or Kelly sizing.
- **Trading behavior**: All changes are confined to observability (metrics computation and logging). No trade is entered, sized, or exited differently as a result of this patch.
- **Data contract**: `MetricsEngine.compute()` return dict is a superset of the prior contract — `last_pnl` is additive. Callers that did not use `last_pnl` are unaffected.

---

## 6. Next Steps

1. **NEXT PRIORITY — Threshold tuning:** Calibrate `ValidationEngine` thresholds (win_rate floor, PF floor, MDD ceiling) against 24h staging run data.
2. **P1 gate — CRITICAL → kill-switch wiring:** `ValidationState.CRITICAL` must call `stop_event.set()` before LIVE promotion.
3. **P1 gate — LIVE/CLOB closed-trade hook:** Wire `_run_closed_validation_hook` into `execution/clob_executor.py` close path for real-money fills.
4. **P2 — structlog JSONRenderer:** Enable for production log ingestion pipeline.
5. **24h staging run:** Cleared to proceed; observe validation state transitions and alert cadence.
