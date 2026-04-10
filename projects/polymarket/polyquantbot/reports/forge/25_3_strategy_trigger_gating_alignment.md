# 25_3_strategy_trigger_gating_alignment

Date: 2026-04-10
Branch: fix/infra-strategy-trigger-gating-alignment-2026-04-10

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target:
- `_persist_trade_intent(...)` exists and is called in `StrategyTrigger.evaluate(...)` before proof creation and execution call.
- Fail-closed behavior blocks runtime path when persistence returns false or raises.
- `AccountEnvelope` exists and is used in the runtime evaluation path.
- Missing risk profile binding blocks with `risk_profile_binding_missing`.
- Tests are discoverable at `projects/polymarket/polyquantbot/tests/test_p25_account_envelope_risk_binding_20260410.py` and contain required cases.
Not in Scope:
- New architecture, wallet system changes, schema expansion, execution redesign.
Suggested Next Step:
- SENTINEL validation required before merge. Source: projects/polymarket/polyquantbot/reports/forge/25_3_strategy_trigger_gating_alignment.md. Tier: MAJOR

## 1. What was built
- Added `AccountEnvelope` runtime contract to strategy-trigger path.
- Added `_persist_trade_intent(...)` fail-closed persistence gate in `StrategyTrigger`.
- Wired account-envelope gate (`risk_profile_binding_missing`) and persistence gate (`trade_intent_persistence_failed`) before proof creation and execution.
- Added focused P25 tests for persistence false/exception/success and account-envelope risk binding behavior.

## 2. Current system architecture
- In the touched entry path of `StrategyTrigger.evaluate(...)`, runtime order is:
  1) risk restore gate,
  2) existing strategy/exposure/timing/quality checks,
  3) pre-trade validator,
  4) account envelope gate,
  5) trade intent persistence gate,
  6) validation proof creation,
  7) execution open call.
- Persistence and account binding are narrow integration in the StrategyTrigger execution entry path only.

## 3. Files created / modified (full paths)
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/strategy_trigger.py` (modified)
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_p25_account_envelope_risk_binding_20260410.py` (new)
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/25_3_strategy_trigger_gating_alignment.md` (new)
- `/workspace/walker-ai-team/PROJECT_STATE.md` (modified)

## 4. What is working
- `_persist_trade_intent(...)` and `trade_intent_writer` symbol are present and reachable.
- `AccountEnvelope` symbol is present and used in runtime path.
- Missing `risk_profile_binding` returns `BLOCKED` with reason `risk_profile_binding_missing`.
- Persistence false/exception blocks before proof/open in tests.
- Required P25 test names exist and pass in targeted run.

## 5. Known issues
- Repo-wide `pytest -k` collection without `PYTHONPATH` in this container fails with `ModuleNotFoundError: projects` due environment path setup.
- Pytest warns about unknown `asyncio_mode` config option in this environment.

## 6. What is next
- Run SENTINEL MAJOR validation against this branch using the declared validation target.
- Confirm command-level discoverability and runtime proofs in sentinel report before merge.
