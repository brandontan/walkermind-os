# 24_15_p7_capital_allocation_position_sizing

## Validation Metadata
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target:
  - execution input layer (position sizing) in `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/strategy_trigger.py`
  - strategy output → sizing bridge via `compute_position_size_from_s4_selection(...)`
  - capital allocation logic for edge/confidence-based scaling and risk constraints
- Not in Scope:
  - execution engine redesign
  - risk rule redesign
  - strategy logic changes
  - Telegram UI changes
  - observability changes
- Suggested Next Step: Codex auto PR review + COMMANDER review required before merge. Source: `projects/polymarket/polyquantbot/reports/forge/24_15_p7_capital_allocation_position_sizing.md`. Tier: STANDARD

## 1. What was built
- Implemented dynamic position sizing in strategy trigger using S4-selected trade context before execution.
- Added `PositionSizingDecision` output contract with:
  - `position_size`
  - `size_reason`
  - `applied_constraints`
  - `normalized_score`
- Added strategy-output → sizing bridge through `compute_position_size_from_s4_selection(...)`.
- Wired sizing into `evaluate(...)` so sizing is applied before `open_position(...)`.
- Added focused P7 tests covering strong/weak edge behavior, missing confidence fallback, cap/exposure constraints, determinism, and S4 integration.

## 2. Current system architecture
Sizing flow for this task scope:
1. S4 aggregation provides `selected_trade` + ranked candidate payload.
2. `compute_position_size_from_s4_selection(...)` resolves selected candidate.
3. `_compute_position_size(...)` computes deterministic score:
   - `edge_norm = clamp(edge / 0.10, 0, 1)`
   - `confidence_val = clamp(confidence, 0, 1)` or `0.35` when missing
   - `base_score = 0.7 * edge_norm + 0.3 * confidence_val`
   - conservative multipliers:
     - missing confidence: `× 0.7`
     - borderline edge (`edge <= min_edge * 1.2`): `× 0.5`
   - `normalized_score = clamp(base_score * conservative_multiplier, 0, 1)`
   - smooth scaling: `scaled_score = normalized_score^2`
   - `raw_size = capital × max_position_size_ratio × scaled_score`
4. Constraints applied in order:
   - total exposure cap (`max_total_exposure_ratio` from execution engine)
   - min position floor (`min_position_size_usd`)
5. Final sizing decision is used by `evaluate(...)` before order open call.

## 3. Files created / modified (full paths)
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/strategy_trigger.py`
- Added: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_p7_capital_allocation_position_sizing_20260409.py`
- Added: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/24_15_p7_capital_allocation_position_sizing.md`
- Modified: `/workspace/walker-ai-team/PROJECT_STATE.md`

## 4. What is working
- Dynamic edge/confidence sizing implemented with deterministic smooth scaling.
- Conservative fallback implemented for:
  - missing confidence
  - borderline edge
- Constraint handling working:
  - per-position cap bounded by `≤ 10%` capital
  - min position threshold enforced
  - total exposure guard respected
- S4 integration working:
  - selected trade is bridged into sizing path
  - sizing output is applied before execution open call

### Runtime proof examples
1) **Strong signal → larger position**
- Input: edge `0.09`, confidence `0.92`, capital `10,000`, exposure `0`
- Output: `position_size=820.84` (larger size, under 10% cap)

2) **Weak signal → small position**
- Input: edge `0.021`, confidence `0.55`, capital `10,000`, exposure `0`
- Output: `position_size=24.34` raw then blocked by min threshold → `position_size=0.0`, constraint includes `min_position_size_floor`

3) **Capped by exposure**
- Input: edge `0.20`, confidence `1.0`, capital `10,000`, current exposure `2,700`
- Exposure limit (`30%`) leaves `300` available
- Output: `position_size=300.0`, constraint includes `total_exposure_cap`

### Test evidence
- `python -m py_compile projects/polymarket/polyquantbot/execution/strategy_trigger.py projects/polymarket/polyquantbot/tests/test_p7_capital_allocation_position_sizing_20260409.py projects/polymarket/polyquantbot/tests/test_s4_strategy_aggregation_prioritization_20260409.py` ✅
- `PYTHONPATH=/workspace/walker-ai-team pytest -q projects/polymarket/polyquantbot/tests/test_p7_capital_allocation_position_sizing_20260409.py projects/polymarket/polyquantbot/tests/test_s4_strategy_aggregation_prioritization_20260409.py` ✅ (`13 passed`)

## 5. Known issues
- P7 sizing integration is narrow to strategy-trigger execution input path and not a full execution-engine redesign.
- Pytest still reports repository-level warning: `Unknown config option: asyncio_mode` (tests pass).

## 6. What is next
- Codex auto PR review + COMMANDER review for STANDARD-tier handoff and merge decision.
