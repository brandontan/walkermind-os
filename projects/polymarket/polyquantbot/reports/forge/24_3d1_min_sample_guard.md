# FORGE-X Report — 24_3d1_min_sample_guard.md

**Phase:** 24.3d1  
**Date:** 2026-04-04  
**Environment:** staging  
**Task:** Enforce minimum sample size before validation state evaluation

---

## 1. What was built

Implemented a minimum-trade guard in the validation path to prevent misleading state classification on undersampled windows:

- `MetricsEngine.compute()` now always includes `trade_count` (`len(trades)`), including when `trades` is empty.
- `ValidationEngine.evaluate(metrics)` now checks `trade_count` at the very top and returns:
  - `INSUFFICIENT_DATA`
  - reason: `minimum 30 trades required`
- Guard executes before all threshold logic and therefore overrides HEALTHY/WARNING/CRITICAL when sample size is below 30.

## 2. Current system architecture

Validation branch in pipeline is now:

`PerformanceTracker.get_recent_trades()`
→ `MetricsEngine.compute(trades)`
→ metrics include `trade_count`
→ `ValidationEngine.evaluate(metrics)`
→ **Guard first:** `trade_count < 30` ⇒ `INSUFFICIENT_DATA`
→ otherwise proceed with existing WR/PF/MDD threshold classification.

No execution-path logic was changed.

## 3. Files created / modified (full paths)

- Modified: `projects/polymarket/polyquantbot/monitoring/metrics_engine.py`
- Modified: `projects/polymarket/polyquantbot/monitoring/validation_engine.py`
- Created: `projects/polymarket/polyquantbot/reports/forge/24_3d1_min_sample_guard.md`
- Modified: `PROJECT_STATE.md`

## 4. What is working

Manual validation scenarios executed:

1. `trade_count = 1` → `INSUFFICIENT_DATA`
2. `trade_count = 29` → `INSUFFICIENT_DATA`
3. `trade_count = 30` → normal validation resumes (existing threshold logic applies)

`trade_count` is present in computed metrics for all tested trade lists, including non-empty and empty-safe paths.

## 5. Known issues

- Existing LIVE promotion P1 gates remain unchanged:
  1. CRITICAL → kill-switch wiring not yet enforced in runtime stop path.
  2. LIVE/CLOB closed-trade validation hook still pending.
- `docs/CLAUDE.md` referenced by process instructions is not present in repository.

## 6. What is next

1. Continue staging validation observation run with the new sample guard enabled.
2. Improve Telegram UX to clearly distinguish `INSUFFICIENT_DATA` from actionable warning/critical alerts.
3. Complete remaining LIVE promotion P1 gates (kill-switch + LIVE closed-trade hook).
