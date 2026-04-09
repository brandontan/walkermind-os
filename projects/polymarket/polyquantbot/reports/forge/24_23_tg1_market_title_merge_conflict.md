# 24_23_tg1_market_title_merge_conflict

## Validation Metadata
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target:
  - execution → position mapping
  - portfolio payload builder
  - Telegram view adapter
  - formatter layer
- Not in Scope:
  - new feature development
  - execution logic changes
  - strategy changes
  - sizing / risk changes
  - UI redesign
  - trade history implementation
- Suggested Next Step: Codex auto PR review + COMMANDER review required before merge. Source: `projects/polymarket/polyquantbot/reports/forge/24_23_tg1_market_title_merge_conflict.md`. Tier: STANDARD

## 1. What was built
- Resolved TG-1 merge-conflict behavior by enforcing `market_title` as canonical position title field across the touched pipeline path.
- Extended execution `Position` contract and `ExecutionEngine.open_position(...)` to carry and persist `market_title` explicitly.
- Ensured execution payload export includes `market_title` for every open position row.
- Updated Telegram portfolio normalization and callback payload normalization to preserve `market_title` instead of dropping it.
- Updated Telegram view adapter to canonicalize mixed legacy title fields into `market_title` once, then render from canonical key.
- Tightened formatter title resolution to prioritize `market_title` and reduce aggressive fallback to `Untitled Market`.
- Added focused regression tests for title preservation, multi-position behavior, deterministic formatting, and execution→payload propagation.

## 2. Current system architecture
Execution/path flow in touched scope now resolves as:
1. `execution.strategy_trigger.evaluate(...)` computes selected candidate and passes explicit `market_title` to `ExecutionEngine.open_position(...)`.
2. `execution.engine.Position` stores `market_title` as a first-class field.
3. `execution.engine.export_execution_payload()` serializes `market_title` in each position object.
4. `telegram.handlers.portfolio_service` keeps `market_title` in normalized `PortfolioPosition` snapshots.
5. `telegram.handlers.callback_router` preserves `market_title` into callback payload.
6. `interface.telegram.view_handler` canonicalizes legacy fields into `market_title` and forwards `position_rows` with canonical title.
7. `interface.ui_formatter` renders market labels using canonical `market_title` first and only falls back when title is truly missing.

## 3. Files created / modified (full paths)
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/models.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/engine.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/strategy_trigger.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/telegram/handlers/portfolio_service.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/telegram/handlers/callback_router.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/interface/telegram/view_handler.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/interface/ui_formatter.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_tg_market_title_merge_conflict_20260409.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/24_23_tg1_market_title_merge_conflict.md`
- Modified: `/workspace/walker-ai-team/PROJECT_STATE.md`

## 4. What is working
Root cause of merge conflict:
- Conflicting field expectations (`market_title` vs `market_question`/`market_name`) caused title drops in intermediate payloads, which could drive formatter fallback behavior.
- The position/payload path did not guarantee explicit `market_title` persistence from execution state.

Field-consistency preservation:
- Canonical field is now `market_title` in touched runtime path.
- Legacy fields are only used as explicit one-time mapping inputs into canonical `market_title` in view adapter compatibility handling.
- Formatter path no longer prioritizes mixed fields before canonical title.

Required test coverage (all pass):
1. position with valid title → rendered correctly
2. multiple positions → all show correct titles
3. same market multiple positions → consistent title
4. no regression to `Untitled Market` when title exists
5. deterministic formatting output for same payload
6. execution→payload `market_title` propagation proof

Runtime proof snapshots:

1) BEFORE (title missing path)
```text
🎯 Position
├ Market: Market legacy-1
├ Side: 🟢 YES
├ Entry: 45.00¢
```

2) AFTER (canonical title preserved)
```text
🎯 Position
├ Market: Will Fed cut rates in June?
├ Side: 🟢 YES
├ Entry: 45.00¢
```

3) Multi-position example
```text
🎯 Position
├ Market: ETH > 6k?
...
🎯 Position
├ Market: SOL > 400?
```

Validation of no mixed field usage in touched path:
- Execution position model/export: canonical `market_title` only.
- Portfolio/callback payload: canonical `market_title` only.
- View adapter explicitly maps legacy keys to canonical `market_title` before render.
- Formatter consumes `market_title` as first source and only falls back when truly missing.

## 5. Known issues
- Legacy/non-canonical keys may still exist in unrelated modules outside this task’s validation target; touched path now canonicalizes them to `market_title` before rendering.
- Existing pytest environment warning persists: `Unknown config option: asyncio_mode`.

## 6. What is next
- Codex auto PR review on changed files and direct dependencies.
- COMMANDER review for STANDARD-tier merge/hold decision.

Report: projects/polymarket/polyquantbot/reports/forge/24_23_tg1_market_title_merge_conflict.md
State: PROJECT_STATE.md updated
