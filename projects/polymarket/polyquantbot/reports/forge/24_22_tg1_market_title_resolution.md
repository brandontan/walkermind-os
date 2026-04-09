# 24_22_tg1_market_title_resolution

## Validation Metadata
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target:
  - position data structure in `/workspace/walker-ai-team/projects/polymarket/polyquantbot/telegram/handlers/portfolio_service.py`
  - execution output mapping in `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/engine.py`
  - portfolio payload builder in `/workspace/walker-ai-team/projects/polymarket/polyquantbot/telegram/handlers/callback_router.py` and `/workspace/walker-ai-team/projects/polymarket/polyquantbot/interface/telegram/view_handler.py`
  - Telegram formatter in `/workspace/walker-ai-team/projects/polymarket/polyquantbot/interface/ui_formatter.py`
- Not in Scope:
  - execution engine strategy/risk decisions
  - strategy logic/scoring changes
  - sizing/risk constant changes
  - Telegram layout redesign
  - trade history features
- Suggested Next Step: Codex auto PR review + COMMANDER review required before merge. Source: `projects/polymarket/polyquantbot/reports/forge/24_22_tg1_market_title_resolution.md`. Tier: STANDARD

## 1. What was built
- Fixed Telegram portfolio title resolution by preserving `market_title` end-to-end across:
  - execution position model + exported execution payload
  - portfolio service normalized position schema
  - callback-router normalized payload
  - Telegram view payload normalization
  - Telegram UI formatter position-card rendering
- Replaced broad title fallback inputs with standardized `market_title` plus context lookup (`question` / `name`) only.
- Added warning-only behavior when title is truly unresolved (`telegram_market_title_missing_fallback`) while keeping UI fallback only for genuinely unresolvable titles.
- Added focused TG-1 tests covering required scenarios and non-regression.

Root cause:
- `market_title` was dropped in callback-router normalization and execution export paths, while formatter relied on mixed field names/fallback-heavy logic. This broke identity continuity and produced `Untitled Market` for valid positions.

## 2. Current system architecture
- Flow now enforced:
  - `ExecutionEngine.open_position(..., market_title=...)` stores title in `Position.market_title`
  - `export_execution_payload()` emits `{market_id, market_title, ...}` per position
  - portfolio service + callback router normalize and retain `market_title`
  - view adapter normalizes any legacy row keys into `market_title`
  - formatter displays `market_title` first, then market-context lookup, and falls back to `Untitled Market` only when both are unresolved
- Claim level remains narrow integration in Telegram portfolio rendering surfaces; broader market metadata infrastructure is unchanged.

## 3. Files created / modified (full paths)
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/models.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/engine.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/strategy_trigger.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/telegram/handlers/portfolio_service.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/telegram/handlers/callback_router.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/interface/telegram/view_handler.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/interface/ui_formatter.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_tg1_market_title_resolution_20260409.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/24_22_tg1_market_title_resolution.md`
- Modified: `/workspace/walker-ai-team/PROJECT_STATE.md`

## 4. What is working
Required tests implemented and passing:
1. position with valid title -> displayed correctly
2. multiple positions -> all show correct titles
3. same market multiple positions -> consistent title
4. missing title -> fallback only when truly absent (with cache/context recovery)
5. no regression in portfolio rendering

Additional mapping checks implemented and passing:
- execution output payload includes `market_id` + `market_title`
- portfolio payload builder keeps `market_title` from primary normalized position

Test evidence:
- `python -m py_compile projects/polymarket/polyquantbot/execution/models.py projects/polymarket/polyquantbot/execution/engine.py projects/polymarket/polyquantbot/execution/strategy_trigger.py projects/polymarket/polyquantbot/interface/telegram/view_handler.py projects/polymarket/polyquantbot/interface/ui_formatter.py projects/polymarket/polyquantbot/telegram/handlers/callback_router.py projects/polymarket/polyquantbot/telegram/handlers/portfolio_service.py projects/polymarket/polyquantbot/tests/test_tg1_market_title_resolution_20260409.py` ✅
- `PYTHONPATH=/workspace/walker-ai-team pytest -q projects/polymarket/polyquantbot/tests/test_tg1_market_title_resolution_20260409.py projects/polymarket/polyquantbot/tests/test_telegram_portfolio_position_render_mismatch_20260409.py` ✅ (10 passed, environment warning: unknown `asyncio_mode`)

Runtime proof:
1) Telegram output BEFORE fix behavior (missing title unresolved)
```text
🎯 Position
├ Market: Untitled Market
...
```

2) Telegram output AFTER fix behavior (resolved title displayed)
```text
🎯 Position
├ Market: Will ETH close above $4,000 this week?
...
```

3) Telegram output AFTER fix with multiple positions
```text
🎯 Position
├ Market: Will BTC close above $100k this month?
...
🎯 Position
├ Market: Will BTC close above $100k this month?
...
🎯 Position
├ Market: Will SOL close above $300 this month?
...
```

## 5. Known issues
- When both payload `market_title` and market-context resolution are unavailable, UI still intentionally falls back to `Untitled Market` and logs a warning (expected safe fallback).
- External market-context endpoint may be unreachable in container environments; fallback and warnings are expected in that case.
- Existing pytest warning remains: `Unknown config option: asyncio_mode`.

## 6. What is next
- Codex auto PR review on changed files + direct dependencies.
- COMMANDER review for STANDARD-tier merge/hold decision.

Report: projects/polymarket/polyquantbot/reports/forge/24_22_tg1_market_title_resolution.md
State: PROJECT_STATE.md updated
