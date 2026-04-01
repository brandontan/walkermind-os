# Phase 9 — Stability Audit & Fix: COMPLETE

**Project:** Walker AI Trading Team — PolyQuantBot
**Engineer:** FORGE-X
**Date:** 2026-03-30
**Branch:** `feature/forge/polyquantbot-phase9-stability-fix`
**Status:** ✅ All identified runtime, logic, and integration issues resolved

---

## What Was Built

A full audit of Phase 9 and Phase 8 modules to identify and fix all issues
that could prevent a reliable 24-hour DRY_RUN paper trading session.

---

## Bugs Found and Fixed

### 1. `phase9/metrics_validator.py` — p95 Latency Index Off-by-One (Critical)

**Bug:** `_compute_p95_latency()` used `int(N * 0.95) - 1` (floor) to compute
the 95th-percentile index. For sample sizes where `0.95 * N` is not an integer
the floor operation selects a value below the true 95th percentile.

Examples:
- N=10: `int(9.5)-1 = 8` → selects 9th of 10 values (p90), not p95
- N=5:  `int(4.75)-1 = 3` → selects 4th of 5 values (p80), not p95

**Impact:** GO-LIVE gate would falsely report a p95 latency lower than the
real value, potentially letting a high-latency system through the gate.

**Fix:** Added `import math` and replaced `int(N * 0.95) - 1` with
`math.ceil(N * 0.95) - 1` (nearest-rank method).

---

### 2. `phase9/main.py` — `task.exception()` Raises on Cancelled Tasks (Critical)

**Bug:** In `Phase9Orchestrator.run()`, after `asyncio.wait(..., return_when=FIRST_EXCEPTION)`,
the code called `task.exception()` on every completed task without first
checking `task.cancelled()`. Calling `task.exception()` on a cancelled task
raises `CancelledError`, which would crash the `run()` method and bypass
the graceful shutdown path.

**Fix:**
- Added `if task.cancelled(): continue` before calling `task.exception()`.
- Added explicit cancellation and `asyncio.gather()` for any `pending` tasks
  that remain when `FIRST_EXCEPTION` returns early, preventing task leaks.

---

### 3. `phase9/main.py` — Double-Shutdown Race Condition (High)

**Bug:** `shutdown()` used a simple `if not self._running: return` guard.
If two callers (e.g. SIGTERM signal handler + `_duration_timer`) reached
`shutdown()` concurrently, both would pass the check before either set
`self._running = False`. This could lead to double cancellation of tasks,
double Telegram alerts, and double metrics writes.

**Fix:** Wrapped the `_running` check and assignment in an `asyncio.Lock`
(`self._shutdown_lock`). The lock is created in `__init__` so it is always
available when `shutdown()` is called.

---

### 4. `phase9/main.py` — `asyncio.get_event_loop()` Deprecated Inside Async Context (Medium)

**Bug:** `_async_main()` called `asyncio.get_event_loop()` to get the loop
for signal handler installation. Inside a coroutine running under `asyncio.run()`,
`get_event_loop()` is deprecated in Python 3.10+ and may emit DeprecationWarnings
or behave unexpectedly with custom event loop policies.

**Fix:** Replaced `asyncio.get_event_loop()` with `asyncio.get_running_loop()`
which is the correct and efficient call inside an already-running async context.

---

### 5. `phase9/decision_callback.py` — `_get_open_market_ids()` Always Returns Empty List (Medium)

**Bug:** `_get_open_market_ids()` was a synchronous method that always
returned `[]`. The comment correctly stated that PositionTracker is the
authoritative source, but no reference to PositionTracker was injected into
`DecisionCallback`, so the Phase 6.6 correlation filter received an empty
open-positions list for every decision. This meant:
- Correlation-based position limit enforcement was silently disabled.
- Multiple positions in correlated markets could be opened simultaneously,
  violating the `correlation_limit: 0.40` config constraint.

**Fix:**
- Added optional `position_tracker=None` parameter to `DecisionCallback.__init__()`.
  Adding it as optional preserves backward compatibility with existing callers.
- `_get_open_market_ids()` is now an `async` method that calls
  `position_tracker.open_positions_snapshot()` and extracts market IDs.
  Falls back to `[]` if position_tracker is None or raises.
- Updated `_run_pipeline` to `await self._get_open_market_ids()` before
  calling `apply_sizing()`.
- Updated `Phase9Orchestrator.bootstrap()` to pass `position_tracker` to
  `DecisionCallback`.

---

## Files Modified

| File | Changes |
|------|---------|
| `phase9/metrics_validator.py` | Added `import math`; fixed p95 index: `math.ceil(N*0.95)-1` |
| `phase9/main.py` | Fixed `task.exception()` on cancelled tasks; cancel pending tasks on early exit; shutdown double-call lock; `get_running_loop()`; pass `position_tracker` to DecisionCallback |
| `phase9/decision_callback.py` | Added `position_tracker` optional param; made `_get_open_market_ids()` async with real PositionTracker data; await the call in `_run_pipeline` |

---

## What's Working

- **p95 latency gate** now correctly reflects the true 95th-percentile latency.
- **run() loop** no longer crashes when background tasks are cancelled.
- **shutdown()** is idempotent and safe under concurrent invocation.
- **Correlation filter** now receives the real set of open market IDs.
- **No blocking calls** — all external I/O remains async with timeouts.
- **All safety mechanisms** (kill switch, circuit breaker, heartbeat) unchanged and validated.

## Known Issues

None identified beyond those fixed above.

## What's Next (Phase 10 / GO-LIVE)

- Run the 24h paper session with the fixes applied.
- Confirm MetricsValidator gate outputs correct p95 in `metrics.json`.
- Once all gate checks pass, proceed to Phase 10: live capital deployment.
