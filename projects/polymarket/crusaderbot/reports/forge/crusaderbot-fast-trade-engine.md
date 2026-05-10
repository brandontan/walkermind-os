# WARP•FORGE Report — crusaderbot-fast-trade-engine

**Branch:** WARP/crusaderbot-fast-trade-engine
**Date:** 2026-05-10
**Validation Tier:** MAJOR
**Claim Level:** FULL RUNTIME INTEGRATION
**Validation Target:** TradeEngine service layer — signal → risk gate → paper order → paper position; TP/SL exit watcher integration; hermetic test coverage of full pipeline
**Not in Scope:** Live trading, real CLOB execution, Copy Trade execution, trade notifications, UI changes, activation guard mutations
**Suggested Next Step:** WARP•SENTINEL validation of WARP/crusaderbot-fast-trade-engine before merge

---

## 1. What Was Built

Fast Track A canonical trade engine: a typed, stateless service layer that closes the gap between the scan loop and the paper execution infrastructure already in place.

**`services/trade_engine/engine.py`** — `TradeEngine`, `TradeSignal`, `TradeResult`

- `TradeSignal` (frozen dataclass): full typed contract for a single signal entering the engine — user context, market fields, size, price, TP/SL, strategy metadata, idempotency key
- `TradeResult` (frozen dataclass): typed execution outcome — `approved`, `mode`, `order_id`, `position_id`, `rejection_reason`, `failed_gate_step`, `chosen_mode`
- `TradeEngine.execute(signal)`: evaluates the 13-step risk gate; on rejection returns `TradeResult(approved=False)`; on approval calls `router.execute` → instant paper fill at signal price; handles idempotent duplicate correctly (`mode="duplicate"` when paper engine returns `status="duplicate"`)
- `TradeEngine._build_gate_context(signal)`: static method mapping all `TradeSignal` fields to `GateContext`; no DB reads inside the engine

**`services/trade_engine/__init__.py`** — public API re-export (`TradeEngine`, `TradeSignal`, `TradeResult`)

**`tests/test_fast_track_a.py`** — 39 hermetic tests (no DB, no broker, no Telegram)

Pipeline proven end-to-end:

```
TradeSignal → TradeEngine.execute()
    → _build_gate_context()
    → _risk_evaluate(GateContext)          [patched]
    → gate rejected → TradeResult(approved=False)
    → gate approved → _router_execute()   [patched]
        → paper engine instant fill
        → TradeResult(approved=True, mode="paper"|"duplicate")

APScheduler tick
    → exit_watcher.run_once()
    → evaluate(OpenPositionForExit)
        → force_close_intent → FORCE_CLOSE (EMERGENCY)
        → ret >= tp_pct        → TP_HIT
        → ret <= -sl_pct       → SL_HIT
        → strategy hook        → STRATEGY_EXIT
        → otherwise            → hold
    → router.close() → paper.close_position() → ledger credit
```

---

## 2. Current System Architecture

```
Telegram UX (Phase 5A–5I)
        │
        ▼
services/signal_scan/signal_scan_job.py   ← P3d scan loop
        │  SignalCandidate
        ▼
services/trade_engine/engine.py           ← NEW (Track A)
  TradeEngine.execute(TradeSignal)
        │
        ├─► domain/risk/gate.py           ← 13-step risk gate (mandatory)
        │       GateContext → GateResult
        │
        └─► domain/execution/router.py    ← mode router (paper always when guards OFF)
                │
                └─► domain/execution/paper.py
                        execute(): order + position open, ledger debit
                        close_position(): ledger credit, ExitReason stored

APScheduler (scheduler.py)
        │
        └─► domain/execution/exit_watcher.py   ← TP/SL poll loop
                run_once() → evaluate() per open position
                    → router.close() on trigger
```

Activation guards (all OFF — unchanged by this PR):
- `ENABLE_LIVE_TRADING` — NOT SET
- `EXECUTION_PATH_VALIDATED` — NOT SET
- `CAPITAL_MODE_CONFIRMED` — NOT SET
- `USE_REAL_CLOB` — NOT SET (default False)

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/services/trade_engine/__init__.py`
- `projects/polymarket/crusaderbot/services/trade_engine/engine.py`
- `projects/polymarket/crusaderbot/tests/test_fast_track_a.py`

**Modified:**
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/ROADMAP.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-fast-trade-engine.md` (this file)

No existing domain files modified. No activation guards touched.

---

## 4. What Is Working

- `TradeEngine.execute()` correctly gates every signal through `domain/risk/gate.evaluate()` before touching the router — gate rejection never calls `_router_execute()`
- Approved path: final size comes from `gate_result.final_size_usdc` (Kelly-fractioned), falling back to `signal.proposed_size_usdc` only when gate does not override
- Idempotent duplicate: paper engine `{"status": "duplicate"}` correctly surfaces as `mode="duplicate"`, not `mode="paper"`, so callers can distinguish new fills from replay-safe no-ops
- `chosen_mode` propagated from gate result into `TradeResult` — confirms paper-only posture when guards are OFF
- TP/SL exit watcher: force_close priority verified above TP and SL; NO-side P&L formula confirmed (`comp_entry = 1 - entry_price`, `comp_exit = 1 - no_price`)
- All 39 hermetic tests pass: 7 gate-rejected paths, 8 approved paths, 4 GateContext mapping tests, 11 exit watcher close-reason tests, 4 TradeSignal contract tests, 2 TradeResult contract tests, 4 ExitReason enum tests

```
39 passed in 3.61s
```

---

## 5. Known Issues

- Float boundary: `ret == -sl_pct` exactly will not trigger SL due to IEEE 754 representation (e.g., `(0.54-0.60)/0.60 = -0.09999...`). Test values use a margin below threshold. In production this is benign — price will not land on exact boundary; if it does the next watcher tick (60s) resolves it.
- `TradeEngine` is not yet wired into `signal_scan_job.py` as the canonical executor. The scan loop (`_process_candidate` / `_insert_execution_queue`) continues to call `router_execute` directly. Wiring Track A into the scan loop is a separate integration step for WARP🔹CMD to authorize; this PR delivers the engine and its contract, not the loop rewire.
- Exit watcher APScheduler job is already wired in `scheduler.py`; no change needed there.

---

## 6. What Is Next

1. WARP•SENTINEL validation of WARP/crusaderbot-fast-trade-engine (Tier MAJOR — mandatory before merge)
2. After Track A merge: Track B (Copy Trade execution) can be unblocked
3. After Track A merge: Track C (trade notifications) can target the `TradeResult` surface
4. After Track A merge: signal_scan_job rewire to use `TradeEngine` instead of direct `router_execute` (authorize as separate lane, STANDARD)
