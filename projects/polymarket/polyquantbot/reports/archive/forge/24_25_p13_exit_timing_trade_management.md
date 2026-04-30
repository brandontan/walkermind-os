# 24_25_p13_exit_timing_trade_management

## Validation Metadata
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target:
  - position monitoring loop in `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/strategy_trigger.py`
  - adaptive exit decision logic (`EXIT_FULL` / `HOLD`)
  - integration points with P9 adaptive feedback and P11 regime context
- Not in Scope:
  - execution engine redesign
  - strategy entry logic changes
  - Telegram UI redesign
  - external integrations
- Suggested Next Step: Codex auto PR review + COMMANDER review required before merge. Source: `projects/polymarket/polyquantbot/reports/forge/24_25_p13_exit_timing_trade_management.md`. Tier: STANDARD

## 1. What was built
- Added adaptive exit-management configuration and deterministic `ExitDecision` contract in strategy trigger scope.
- Implemented context-aware exit evaluator with required output fields:
  - `exit_decision`
  - `exit_reason`
  - `pnl_snapshot`
  - `trade_duration`
- Implemented required exit logic:
  1. **Take-profit management**: winners are held while momentum remains intact and exited when favorable move weakens.
  2. **Stop-loss management**: immediate full-exit on adverse move beyond bounded loss threshold or signal invalidation.
  3. **Time-based exit**: stale-trade timeout and hard max-duration guard to prevent infinite holding.
- Integrated adaptive behavior (light):
  - **P11 regime context** adjusts exit aggressiveness (`LOW_ACTIVITY_CHAOTIC` exits faster; strong regimes hold longer).
  - **P9 performance feedback** (adaptive strategy-weight state) tightens/loosens exit factor based on recent strategy quality.
- Wired exit decision into live position monitoring branch of `evaluate(...)` so the monitoring loop now closes based on adaptive exit decisions, not static fixed-PnL threshold only.

## 2. Current system architecture
- Entry-side flow from earlier tasks remains unchanged (P12 timing + P10 quality + P8/P7 sizing/exposure gating).
- Position monitoring flow is now:
  1. mark-to-market update
  2. fetch tracked open position
  3. call `evaluate_exit_decision(...)`
  4. if `HOLD` -> keep position open
  5. if `EXIT_FULL` -> close position and emit close trace
- Exit evaluator inputs:
  - position state (`pnl`, `entry_price`, `current_price`, `size`, `created_at`)
  - P11 regime context (`aggregation_decision.current_regime` or context override)
  - P9 adaptive state (`get_adaptive_adjustment_state()` average strategy-weight signal)
- Safety controls:
  - bounded thresholds via clamp
  - hard max duration guard
  - deterministic branch ordering and fixed reason strings

## 3. Files created / modified (full paths)
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/strategy_trigger.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_p13_exit_timing_trade_management_20260409.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/24_25_p13_exit_timing_trade_management.md`
- Modified: `/workspace/walker-ai-team/PROJECT_STATE.md`

## 4. What is working
Required tests (all pass):
1. profitable trade -> hold then exit on weakening momentum
2. losing trade -> stop loss triggers
3. stale trade -> time exit
4. regime + feedback context affects exit behavior
5. deterministic output for same input

Test evidence:
- `python -m py_compile projects/polymarket/polyquantbot/execution/strategy_trigger.py projects/polymarket/polyquantbot/tests/test_p13_exit_timing_trade_management_20260409.py` ✅
- `PYTHONPATH=/workspace/walker-ai-team pytest -q projects/polymarket/polyquantbot/tests/test_p13_exit_timing_trade_management_20260409.py projects/polymarket/polyquantbot/tests/test_p9_performance_feedback_loop_20260409.py projects/polymarket/polyquantbot/tests/test_p11_market_regime_detection_20260409.py` ✅ (17 passed, environment warning: unknown `asyncio_mode`)

Runtime proof:
1) winning trade -> delayed exit
```text
winning trade hold: ExitDecision(exit_decision='HOLD', exit_reason='favorable_momentum_intact', pnl_snapshot=60.0, trade_duration=1000)
winning trade delayed exit: ExitDecision(exit_decision='EXIT_FULL', exit_reason='momentum_weakened_after_favorable_move', pnl_snapshot=30.0, trade_duration=1010)
```
2) losing trade -> fast exit
```text
losing trade fast exit: ExitDecision(exit_decision='EXIT_FULL', exit_reason='stop_loss_threshold_breached', pnl_snapshot=-50.0, trade_duration=1020)
```
3) stale trade -> timeout exit
```text
stale trade timeout exit: ExitDecision(exit_decision='EXIT_FULL', exit_reason='stale_trade_timeout', pnl_snapshot=0.5, trade_duration=2000)
```

## 5. Known issues
- P13 is intentionally narrow integration in strategy-trigger position monitoring path and is not yet generalized to other runtime orchestration surfaces.
- `EXIT_PARTIAL` is intentionally not activated in this pass (optional output remains reserved).
- Existing test environment warning persists: `Unknown config option: asyncio_mode`.

## 6. What is next
- Codex auto PR review on changed files + direct dependencies.
- COMMANDER review for STANDARD-tier merge/hold decision.

Report: projects/polymarket/polyquantbot/reports/forge/24_25_p13_exit_timing_trade_management.md
State: PROJECT_STATE.md updated
