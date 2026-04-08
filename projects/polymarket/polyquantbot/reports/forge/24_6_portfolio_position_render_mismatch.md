# 24_6_portfolio_position_render_mismatch

## Validation Metadata
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target:
  - Telegram portfolio positions view rendering path via `projects/polymarket/polyquantbot/interface/telegram/view_handler.py`
  - Premium UI position-card rendering path via `projects/polymarket/polyquantbot/interface/ui_formatter.py`
  - Data-source consistency between summary position count and rendered position list
- Not in Scope:
  - execution logic
  - risk logic
  - position sizing
  - strategy logic
  - order placement
  - observability system
  - UI redesign
- Suggested Next Step: Codex auto PR review + COMMANDER review required before merge. Source: `projects/polymarket/polyquantbot/reports/forge/24_6_portfolio_position_render_mismatch.md`. Tier: STANDARD

## 1. What was built
- Fixed Telegram positions view rendering mismatch so summary count and rendered position cards are produced from the same underlying `positions` dataset.
- Removed count drift by deriving `positions_count` from actual position rows whenever rows exist (instead of trusting potentially stale external `positions_count` values).
- Added full multi-row position-card rendering in premium UI for `positions` mode so all active positions are displayed (including same-market / same-side entries).
- Added focused regression tests covering same-market multi-position rendering, different-market rendering, summary-to-render count parity, and similar-ID non-overwrite behavior.

## 2. Current system architecture
- `render_view("positions", payload)` now computes metrics from `_position_rows(payload)` and carries the exact row list into UI payload as `position_rows`.
- `_base_payload(... )` uses that same derived metrics object for:
  - `positions` summary value
  - `largest_position_size`
  - unrealized aggregation
  - `position_rows` handoff
- `render_dashboard(... )` for `mode == "positions"` now renders one position card per row from `position_rows` via `_render_position_cards(...)` (list-based iteration, no dict-key grouping).
- Result: summary + rendered cards share one data source and cannot diverge due to stale count or key collision in render mapping.

## 3. Files created / modified (full paths)
- Modified: `projects/polymarket/polyquantbot/interface/telegram/view_handler.py`
- Modified: `projects/polymarket/polyquantbot/interface/ui_formatter.py`
- Created: `projects/polymarket/polyquantbot/tests/test_telegram_portfolio_position_render_mismatch_20260409.py`
- Created: `projects/polymarket/polyquantbot/reports/forge/24_6_portfolio_position_render_mismatch.md`
- Modified: `PROJECT_STATE.md`

## 4. What is working
- Multiple positions in the same market now render as separate cards (no subset drop).
- Multiple positions across different markets all render in the same positions view.
- Summary open-position count matches rendered card count because both derive from the same rows list.
- Similar position IDs do not collide in rendering because rendering iterates row-by-row without key-based overwrite.

Required tests (focused):
- Multiple positions same market → both rendered ✅
- Multiple positions different markets → all rendered ✅
- Summary count matches rendered count ✅
- No overwrite when IDs are similar ✅

Runtime proof:
- raw positions list length = 3
- rendered output visible entries (`🎯 Position`) = 3
- summary count line (`Open Positions`) = 3

Commands run:
- `python -m py_compile projects/polymarket/polyquantbot/interface/telegram/view_handler.py projects/polymarket/polyquantbot/interface/ui_formatter.py projects/polymarket/polyquantbot/tests/test_telegram_portfolio_position_render_mismatch_20260409.py` ✅
- `PYTHONPATH=/workspace/walker-ai-team pytest -q projects/polymarket/polyquantbot/tests/test_telegram_portfolio_position_render_mismatch_20260409.py` ✅ (4 passed)
- Runtime proof command (render sample payload through `render_view("positions", ...)`) ✅

## 5. Known issues
- Existing test-environment warning remains: pytest config reports unknown `asyncio_mode` option; focused tests still pass.
- External live Telegram device screenshot proof is unavailable in this container environment.

## 6. What is next
- COMMANDER review for STANDARD-tier narrow integration fix.
- Merge decision after Codex auto PR review baseline + COMMANDER review.
- No SENTINEL escalation required unless COMMANDER explicitly reclassifies task impact.
