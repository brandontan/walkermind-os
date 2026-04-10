# 24_50_public_account_wallet_foundation_fix_fail_closed_persistence_and_default_risk_binding

## Validation Metadata
- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Validation Target:
  1. `StrategyTrigger.evaluate()` blocks before proof creation/execution when trade-intent persistence returns `False`.
  2. `StrategyTrigger.evaluate()` blocks fail-closed before proof creation/execution when trade-intent persistence raises.
  3. Existing execution-boundary fail-closed behavior remains intact in the touched `StrategyTrigger -> ExecutionEngine` path.
  4. Existing successful path still proceeds decision -> persistence -> proof -> execution in touched scope.
- Not in Scope:
  - Schema changes.
  - Orders/fills/positions persistence redesign.
  - Websocket/user reconciliation.
  - Auth vault hardening.
  - Live order submission changes.
  - Public dashboard/UI changes.
  - Runtime account envelope risk-binding subsystem changes (no corresponding implementation surface located in this repository snapshot).
- Suggested Next Step: SENTINEL validation required before merge. Source: `projects/polymarket/polyquantbot/reports/forge/24_50_public_account_wallet_foundation_fix_fail_closed_persistence_and_default_risk_binding.md`. Tier: MAJOR.

## 1. What was built
- Added an explicit trade-intent persistence gate in `StrategyTrigger` via `_persist_trade_intent(...)`.
- Enforced fail-closed behavior: when persistence returns `False` or raises, the flow records a blocked terminal trace and returns `BLOCKED` immediately.
- Reordered entry flow so proof creation (`build_validation_proof`) occurs only after persistence succeeds.

## 2. Current system architecture
- In the touched entry path, runtime sequence is now:
  1. Pre-trade validator ALLOW.
  2. Persist trade intent via configured writer (or default tracker-backed persistence).
  3. If persistence fails (`False` or exception): block with reason `trade_intent_persistence_failed` and stop.
  4. Only on persistence success: build validation proof.
  5. Only then call `ExecutionEngine.open_position(...)`.

## 3. Files created / modified (full paths)
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/strategy_trigger.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_p16_execution_validation_risk_enforcement_20260409.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/24_50_public_account_wallet_foundation_fix_fail_closed_persistence_and_default_risk_binding.md`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/PROJECT_STATE.md`

## 4. What is working
- `trade_intent_writer.write(...) -> False` now blocks execution before proof creation and before `open_position`.
- `trade_intent_writer.write(...)` raising an exception now blocks execution before proof creation and before `open_position`.
- Success path remains functional: on persistence success, proof creation and open-position execution still occur in the touched path.

### Test evidence
From `/workspace/walker-ai-team/projects/polymarket/polyquantbot`:
1. `python -m py_compile execution/strategy_trigger.py tests/test_p16_execution_validation_risk_enforcement_20260409.py`
   - ✅ pass
2. `PYTHONPATH=/workspace/walker-ai-team pytest -q tests/test_p16_execution_validation_risk_enforcement_20260409.py -k "trade_intent_persistence_false_blocks_before_proof_and_open or trade_intent_persistence_exception_blocks_before_proof_and_open or trade_intent_persistence_success_keeps_normal_path"`
   - ✅ pass (`3 passed, 13 deselected`)

## 5. Known issues
- The requested runtime account-envelope/default risk-binding subsystem (including `risk_profiles.config = {}` binding behavior) is not present in this repository snapshot, so that portion is not patched in this changeset.
- Pytest emits environment warning: unknown config option `asyncio_mode`.

## 6. What is next
- Run SENTINEL MAJOR re-validation on this patch scope:
  - `StrategyTrigger` fail-closed persistence gate
  - proof/execution call ordering
  - non-regression of touched successful path
