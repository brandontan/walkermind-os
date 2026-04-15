# Forge Report — Fast Plan Bot

**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** `/plan` Telegram command surface — `PlanEngine.generate_plans()` + `format_plan_list()` + `handle_plan()` + `CommandHandler._handle_plan()`
**Not in Scope:** live order execution, risk guard bypass, ENABLE_LIVE_TRADING, platform-wide strategy refactor, market data ingestion changes, multi-user Telegram routing, wallet or capital mutation, scheduling or automation.
**Suggested Next Step:** Auto PR review (Codex/Gemini/Copilot) + COMMANDER review required. Source: `projects/polymarket/polyquantbot/reports/forge/25_36_fast_plan_bot.md`. Tier: STANDARD.

---

## 1) What was built

**Fast Plan Bot** — a new `/plan` Telegram command that evaluates available market candidates through all three registered strategies (EVMomentum, LiquidityEdge, MeanReversion), applies Kelly-constrained (α = 0.25) position sizing, classifies risk, and delivers a ranked list of advisory TradePlan objects in premium Telegram UI format.

Key components:

- `PlanEngine` — stateless planning engine: evaluates up to N markets per call, aggregates strategy signals, applies risk constants, returns ranked `TradePlan` list (max 5, ranked by EV × confidence).
- `TradePlan` — structured dataclass capturing: plan_id, market_id, market_title, direction, entry_price, target_price, position_size_usdc, expected_value, edge_score, z_score, risk_level, confidence, reasoning, strategy_sources, generated_at.
- `plan_formatter.py` — pure formatting module: converts TradePlan list to STYLE B SPACING SYSTEM V2 Telegram Markdown. Handles empty plans, None, and long titles gracefully.
- `telegram/handlers/plan.py` — handler with module-level dependency injection: pulls markets from injected MarketMetadataCache, runs PlanEngine, returns (text, keyboard) tuple.
- `/plan` routing in `CommandHandler` — single clean dispatch line + `_handle_plan()` method with lazy import and full error isolation.

Plans are **advisory only** — no orders are placed, no capital is committed, no live guard is touched.

---

## 2) Current system architecture

```
/plan (Telegram command)
      ↓
CommandHandler._handle_plan()
      ↓
telegram/handlers/plan.py → handle_plan()
      ↓
_collect_markets() ← MarketMetadataCache (injected)
      ↓
PlanEngine.generate_plans(markets)
      ├── EVMomentumStrategy.evaluate()
      ├── LiquidityEdgeStrategy.evaluate()
      └── MeanReversionStrategy.evaluate()
           ↓ (signals aggregated, Kelly-sized, risk-classified)
      list[TradePlan] (ranked by EV × confidence, max 5)
      ↓
plan_formatter.format_plan_list()
      ↓
Telegram premium UI (text, keyboard)
```

System pipeline compliance:
- DATA → STRATEGY (PlanEngine uses existing strategy layer) → no RISK bypass → no EXECUTION touch → no MONITORING changes
- ENABLE_LIVE_TRADING guard is NOT touched — this is a read-only advisory path

Risk constants enforced:
- Kelly α = 0.25 (constant `_KELLY_FRACTION`)
- Max position ≤ 10% of capital (constant `_MAX_POSITION_PCT`)
- No full Kelly (α = 1.0) path exists anywhere in this module

---

## 3) Files created / modified (full paths)

### Created
- `/home/user/walker-ai-team/projects/polymarket/polyquantbot/strategy/plan_engine.py`
- `/home/user/walker-ai-team/projects/polymarket/polyquantbot/strategy/plan_formatter.py`
- `/home/user/walker-ai-team/projects/polymarket/polyquantbot/telegram/handlers/plan.py`
- `/home/user/walker-ai-team/projects/polymarket/polyquantbot/tests/test_plan_engine_20260415.py`
- `/home/user/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/25_36_fast_plan_bot.md`

### Modified
- `/home/user/walker-ai-team/projects/polymarket/polyquantbot/telegram/command_handler.py`
  - Added: `if cmd == "plan": return await self._handle_plan()` dispatch
  - Added: `async def _handle_plan(self)` method (lazy import + error isolation)
- `/home/user/walker-ai-team/PROJECT_STATE.md`

---

## 4) What is working

- `PlanEngine.generate_plans()` evaluates market candidates across 3 strategies and returns ranked TradePlan list
- Kelly sizing (α = 0.25) enforced with 10% capital cap
- Risk classification (LOW / MEDIUM / HIGH) working correctly
- `format_plan_list()` renders STYLE B premium Telegram UI with all required fields
- Graceful fallback on empty plans, None, low-depth markets, missing market ID
- `/plan` command routed correctly in `CommandHandler`
- `_handle_plan()` isolates errors with structured logging and user-friendly fallback message
- Dependency injection via module-level setters for `MarketMetadataCache`, `SystemStateManager`, mode, and capital
- **30/30 unit tests pass** (0 failures, 0 errors)
- All 5 touched/created files pass `python -m py_compile` cleanly

---

## 5) Known issues

- Strategy rolling windows (EVMomentum window=20, MeanReversion EWMA) need ≥20 price ticks per market to produce signals — fresh sessions may return 0 plans until window fills
- MarketMetadataCache field names are mapped defensively (`condition_id` / `market_id`, `question` / `title`, etc.) — if cache schema changes, field mapping may need update
- Existing pytest warning persists: `Unknown config option: asyncio_mode` (non-runtime hygiene backlog, pre-existing)
- No `/plan [market_id]` targeted planning yet — currently evaluates all cached markets

---

## 6) What is next

- COMMANDER review and auto PR review (Codex/Gemini/Copilot) for STANDARD tier
- Optional: extend `/plan` with `/plan [market_id]` argument for targeted single-market evaluation
- Optional: add `/plan` button shortcut to existing Telegram keyboard menus
- Optional: wire `set_capital()` injection in bot startup to reflect real wallet capital

---

## Validation declaration
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target: `/plan` Telegram command — `PlanEngine.generate_plans()`, `format_plan_list()`, `handle_plan()`, `CommandHandler._handle_plan()`
- Not in Scope: live execution, ENABLE_LIVE_TRADING, risk guard changes, market data ingestion, scheduling, wallet/capital mutation, platform-wide strategy refactor
- Suggested Next Step: Auto PR review (Codex/Gemini/Copilot) + COMMANDER review required

## Pre-flight self-check

```
PRE-FLIGHT CHECKLIST
────────────────────
[x] py_compile — all 5 touched files pass
[x] pytest — 30/30 tests pass (0 failures)
[x] Import chain — all new modules importable
[x] Risk constants — unchanged (α=0.25, max_pos=10%)
[x] No phase*/ folders
[x] No hardcoded secrets
[x] No threading — asyncio only
[x] No full Kelly α=1.0
[x] ENABLE_LIVE_TRADING guard not touched
[x] Forge report exists at correct path with all required sections
[x] PROJECT_STATE.md updated to current truth
[x] ROADMAP.md — no roadmap-level truth changed (STANDARD tier, no phase advancement)
[x] Max 5 files per commit preferred — 5 new files + 1 modified
```

## Validation commands run
1. `python -m py_compile projects/polymarket/polyquantbot/strategy/plan_engine.py projects/polymarket/polyquantbot/strategy/plan_formatter.py projects/polymarket/polyquantbot/telegram/handlers/plan.py projects/polymarket/polyquantbot/tests/test_plan_engine_20260415.py projects/polymarket/polyquantbot/telegram/command_handler.py`
2. `PYTHONPATH=. pytest -q projects/polymarket/polyquantbot/tests/test_plan_engine_20260415.py` → 30 passed in 0.26s
3. `find . -type d -name 'phase*'` → 0 results

**Report Timestamp:** 2026-04-15 13:00 UTC
**Role:** FORGE-X (NEXUS)
**Task:** buatkan fast plan bot ready dalam 1-2 hari
**Branch:** `claude/create-fast-plan-bot-44FWR`
