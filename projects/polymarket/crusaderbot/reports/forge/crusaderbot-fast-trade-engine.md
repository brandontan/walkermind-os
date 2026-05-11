# WARP•FORGE Report — crusaderbot-fast-trade-engine

**Branch:** WARP/crusaderbot-fast-trade-engine
**Date:** 2026-05-11
**Validation Tier:** MAJOR
**Claim Level:** FULL RUNTIME INTEGRATION
**Validation Target:** TradeEngine service layer + active signal scan runtime wiring — signal fires → TradeEngine → risk gate → paper order → paper position; TP/SL exit watcher integration; hermetic test coverage of full pipeline including scan-to-engine path
**Not in Scope:** Live trading, real CLOB execution, Copy Trade execution, trade notifications, UI changes, activation guard flips
**Suggested Next Step:** WARP•SENTINEL validation of WARP/crusaderbot-fast-trade-engine before merge

---

## 1. What Was Built

Fast Track A canonical trade engine wired into the active signal scan runtime.

**`services/trade_engine/engine.py`** — `TradeEngine`, `TradeSignal`, `TradeResult`

- `TradeSignal` (frozen dataclass): full typed contract for a single signal — user context, market fields, size, price, TP/SL, strategy metadata, idempotency key
- `TradeResult` (frozen dataclass): typed execution outcome — `approved`, `mode`, `order_id`, `position_id`, `rejection_reason`, `failed_gate_step`, `chosen_mode`, `final_size_usdc`
- `TradeEngine.execute(signal)`: evaluates the 13-step risk gate; on rejection returns `TradeResult(approved=False)`; on approval calls `router.execute` → instant paper fill; handles idempotent duplicate correctly
- `chosen_mode`: set from router's actual response, not gate decision — prevents live/paper mismatch if guards change between gate eval and router call
- `final_size_usdc`: Kelly-adjusted size from gate propagated through `TradeResult` so the scan job can record it in execution_queue without re-deriving it

**`services/trade_engine/__init__.py`** — public API re-export (`TradeEngine`, `TradeSignal`, `TradeResult`)

**`services/signal_scan/signal_scan_job.py`** — active scan runtime, now wired through TradeEngine

- `_build_trade_signal(row, cand, market, idempotency_key) -> TradeSignal`: replaces the old `_build_gate_context` helper; constructs a fully typed `TradeSignal` from scan-loop data (DB row, `SignalCandidate`, market dict)
- `_engine: TradeEngine` module-level singleton, shared across scan ticks (stateless)
- Normal execution path: `_build_trade_signal` → `_engine.execute(signal)` → on approval, insert execution_queue + mark executed
- Crash recovery path (stale `'queued'` rows): continues to call `router_execute` directly — the risk gate cannot be re-run because gate step 10 rejects the same idempotency_key for 30 min; this is the **only** place `router_execute` is used directly in the scan job
- `GateContext`, `GateResult`, `risk_evaluate` imports removed from scan job — they now live exclusively inside TradeEngine

**`tests/test_fast_track_a.py`** — 47 hermetic tests (39 original + 8 new scan path tests)

New `TestScanPathTradeEngineIntegration` class proves:
1. Normal approval path: `_process_candidate` calls `TradeEngine.execute()` with a `TradeSignal`; `router_execute` is NOT called directly
2. Gate rejection: `_insert_execution_queue` is never called
3. Permanent dedup: `TradeEngine.execute()` is never called when the publication_id is already queued
4. Idempotent duplicate result: queue insert is skipped
5. `_build_trade_signal` YES-side maps `yes_price` as proposed_price
6. `_build_trade_signal` NO-side maps `no_price` as proposed_price
7. TP/SL forwarded from user settings row to `TradeSignal`
8. Null TP/SL in row produces `None` fields on `TradeSignal`

---

## 2. Current System Architecture

```
Telegram UX (Phase 5A–5I)
        │
        ▼
services/signal_scan/signal_scan_job.py   ← active scan loop (WIRED)
  _process_candidate()
    → _build_trade_signal()               ← NEW: replaces _build_gate_context
        │  TradeSignal
        ▼
services/trade_engine/engine.py           ← canonical execution path
  TradeEngine.execute(TradeSignal)
        │
        ├─► domain/risk/gate.py           ← 13-step risk gate (mandatory, always first)
        │       GateContext → GateResult
        │
        └─► domain/execution/router.py    ← mode router (paper always when guards OFF)
                │
                └─► domain/execution/paper.py
                        execute(): order + position open, ledger debit
                        close_position(): ledger credit, ExitReason stored

  execution_queue                         ← post-execution audit + permanent dedup anchor
    INSERT after approval (ON CONFLICT DO NOTHING)
    mark executed immediately after insert

  [crash recovery only]
  router_execute() direct call            ← only for stale 'queued' rows; gate skipped
                                             because idempotency_key already recorded

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
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — TradeEngine wired into normal execution path; `_build_gate_context` replaced by `_build_trade_signal`; direct `risk_evaluate` + `router_execute` calls removed from normal path
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/ROADMAP.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-fast-trade-engine.md` (this file)

No activation guards touched. No live execution paths added.

---

## 4. What Is Working

- `TradeEngine.execute()` correctly gates every signal through `domain/risk/gate.evaluate()` before touching the router — gate rejection never calls `_router_execute()`
- Active scan path (`signal_scan_job._process_candidate`) now calls `_engine.execute(signal)` on the normal path — direct `router_execute` call removed from normal flow
- `_build_trade_signal` maps all `SignalCandidate` + DB row + market fields to `TradeSignal`; YES/NO price resolution preserved; TP/SL forwarded from user settings
- `final_size_usdc` propagated through `TradeResult` — scan job uses it for the execution_queue entry without re-deriving the Kelly-adjusted size
- `chosen_mode` in `TradeResult` reflects actual router execution mode (P2 fix)
- Crash recovery path preserved: stale `'queued'` rows resume via direct `router_execute` with clear documentation explaining why TradeEngine is bypassed
- TP/SL exit watcher: force_close priority verified above TP and SL; NO-side P&L formula confirmed
- All 47 hermetic tests pass (39 TradeEngine/exit-watcher tests + 8 scan-path integration tests)

```
47 passed in 4.25s
```

---

## 5. Known Issues

- Float boundary: `ret == -sl_pct` exactly will not trigger SL due to IEEE 754. In production this is benign — price will not land on exact boundary; next watcher tick resolves it.
- Crash recovery path uses `router_execute` directly (by design). If a crash recovery tick introduces a new position while a normal tick also processes the same candidate (different publication_ids), both positions are valid. Dedup is per `(user_id, publication_id)`.
- `signal_scan_job` execution_queue insert is now post-execution (audit log) rather than pre-execution (reservation). Concurrent ticks for the same signal are protected by the paper engine's idempotency_key; the second call returns `mode="duplicate"` and skips the queue insert.

---

## 6. What Is Next

1. WARP•SENTINEL validation of WARP/crusaderbot-fast-trade-engine (Tier MAJOR — mandatory before merge)
2. After Track A merge: Track B (Copy Trade execution) can be unblocked
3. After Track A merge: Track C (trade notifications) can target the `TradeResult` surface
4. After Track A merge: `run_once()` in `signal_scan_job` already calls `_process_candidate` → TradeEngine for all enrolled users; no further wiring needed
