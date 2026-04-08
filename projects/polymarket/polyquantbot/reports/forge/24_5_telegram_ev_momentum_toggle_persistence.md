# 24_5_telegram_ev_momentum_toggle_persistence

## Validation Metadata
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target:
  - `projects/polymarket/polyquantbot/telegram/handlers/callback_router.py`
  - `projects/polymarket/polyquantbot/tests/test_telegram_ev_momentum_toggle_persistence_20260409.py`
  - Telegram strategy settings menu render/readback path for `ev_momentum`
- Not in Scope:
  - strategy logic changes
  - execution logic
  - risk logic
  - Telegram observability changes
  - other unrelated Telegram menus
  - feature expansion
  - refactor outside toggle persistence path
- Suggested Next Step: Codex auto PR review + COMMANDER review required before merge. Source: `projects/polymarket/polyquantbot/reports/forge/24_5_telegram_ev_momentum_toggle_persistence.md`. Tier: STANDARD

## 1. What was built
- Fixed Telegram strategy toggle persistence ordering for `ev_momentum` (and shared strategy toggle path) by moving DB save to run **after** in-memory toggle mutation.
- Kept existing callback/action contract unchanged (`action:strategy_toggle:<name>` / `strategy_toggle:<name>`) and preserved normalized strategy re-render path.
- Added focused regression tests for callback payload mapping, persistence write state, deterministic OFF→ON behavior, menu readback, and non-regression for another strategy toggle.

## 2. Current system architecture
- Strategy toggle callback flow now executes in this sequence:
  1. Callback action parsed as `strategy_toggle:<name>`
  2. `handle_strategy_toggle(strategy_name)` mutates `StrategyStateManager` in-memory state
  3. `StrategyStateManager.save(db=...)` persists the **updated** state snapshot
  4. `_render_normalized_callback("strategy")` re-renders menu based on the same strategy state source
- This removes stale-state persistence where writes could capture pre-toggle values.

## 3. Files created / modified (full paths)
- Modified: `projects/polymarket/polyquantbot/telegram/handlers/callback_router.py`
- Created: `projects/polymarket/polyquantbot/tests/test_telegram_ev_momentum_toggle_persistence_20260409.py`
- Created: `projects/polymarket/polyquantbot/reports/forge/24_5_telegram_ev_momentum_toggle_persistence.md`
- Modified: `PROJECT_STATE.md`

## 4. What is working
- `ev_momentum` ON toggle now persists as ON after callback handling.
- Strategy menu re-render/readback shows `ev_momentum` active after enable.
- OFF→ON toggle sequence for `ev_momentum` is deterministic and persisted in order.
- Callback payload/action mapping remains aligned with strategy key:
  - payload includes `action:strategy_toggle:ev_momentum`
  - dispatch route parses `strategy_toggle:ev_momentum`
- Non-regression check confirms toggling `mean_reversion` does not alter `ev_momentum` state.

Focused runtime/test evidence:
- Callback payload proof: `action:strategy_toggle:ev_momentum` asserted in test.
- Persisted state proof after enable: `db.save_strategy_state` call argument contains `{"ev_momentum": True, ...}`.
- Menu render proof after refresh/re-entry path: `settings_strategy` dispatch contains `EV MOMENTUM` with `Status: ✅ ACTIVE` after enable.
- Non-regression proof: `mean_reversion` toggle changes only `mean_reversion` while `ev_momentum` remains unchanged.

Checks run:
- `python -m py_compile projects/polymarket/polyquantbot/telegram/handlers/callback_router.py projects/polymarket/polyquantbot/tests/test_telegram_ev_momentum_toggle_persistence_20260409.py` ✅
- `PYTHONPATH=/workspace/walker-ai-team pytest -q projects/polymarket/polyquantbot/tests/test_telegram_ev_momentum_toggle_persistence_20260409.py` ✅ (4 passed)

## 5. Known issues
- Pytest emits existing environment warning: unknown `asyncio_mode` config option. Focused tests still pass.
- This task does not add external live Telegram screenshot evidence (container-limited runtime environment).

## 6. What is next
- COMMANDER review for STANDARD-tier narrow integration fix and focused persistence evidence.
- Merge decision after Codex auto PR review baseline and COMMANDER review.
- No SENTINEL escalation required for this task tier/scope.

Root cause found:
- In `CallbackRouter._dispatch`, the strategy persistence call (`self._strategy_state.save(db=self._db)`) executed **before** `handle_strategy_toggle(strategy_name)`, so stored state could remain OFF even when user toggled ON.
