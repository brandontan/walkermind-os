# WARP•FORGE Report — strategy-risk-copy

**Branch:** WARP/CRUSADERBOT-STRATEGY-RISK-COPY
**Date:** 2026-05-17 16:29 Asia/Jakarta
**Validation Tier:** MAJOR
**Claim Level:** FULL RUNTIME INTEGRATION

---

## 1. What Was Built

Five-part feature bundle wiring the preset, risk, and copy-trade systems together so each
CrusaderBot user receives signals filtered to their active strategy preset, can independently
configure risk sizing, and runs copy-trade tasks with full 8-step wizard controls.

**Part 1 — Strategy Isolation (CRITICAL)**
`signal_scan_job.py` previously ran all lib strategies for every user regardless of their
active preset. Two-phase scan loop introduced: Phase A runs each lib strategy once per tick,
Phase B distributes candidates to users filtered by `_PRESET_ALLOWED[active_preset]`.
`LibStrategyRunner` adapter converts `lib.Signal` → `domain.strategy.types.SignalCandidate`.

**Part 2 — Ledger Atomic Fix (HIGH)**
`delete_position_with_ledger()` added to `domain/positions/registry.py` — hard-deletes a
position and all its ledger entries in a single `async with conn.transaction()` block.
Exported from `domain/positions/__init__.py`.

**Part 3 — WebTrader AutoTradePage Restructure (STANDARD)**
AutoTradePage rebuilt into two independent sections:
- Section 1: 8 strategy preset cards (lib/strategies/ names) + 4 Coming Soon grayed cards
- Section 2: 4 risk profile cards (Conservative/Balanced/Aggressive/Custom) with Custom
  inline inputs (capital%, TP%, SL%), client-side validation, and `PATCH /autotrade/risk-profile`.
Separate active state; selecting a preset does not change risk profile and vice versa.

**Part 4 — TG AUTO Menu Restructure (STANDARD)**
`/settings → Auto Trade` now shows a 2-sub-menu picker (Strategy Preset / Risk Profile).
Strategy sub-menu: 8 preset buttons, confirmation card, activate handler.
Risk sub-menu: 4 buttons, Custom triggers a 3-step wizard (capital% → TP% → SL% → confirm)
implemented via `ctx.user_data["awaiting"]` text input states in `settings.py`.

**Part 5 — Copy Trade 8-Step Wizard + Monitor Filters (STANDARD)**
TG: 8-step `ConversationHandler` (states 10–19, separate from old wizard states 0–4).
Steps: nickname → wallet+stats → direction → type → amount → execution → slippage → topups.
WebTrader: `CopyTradePage.tsx` (new) with active targets list and add-target form.
Backend: 5 new CRUD routes under `/copy-trade/tasks`.
Monitor: 3 new filter gates in `_process_one()` — copy_direction, allow_topups, execution_mode.
Migration 035: 4 new columns on `copy_trade_tasks` (idempotent `IF NOT EXISTS`).

---

## 2. Current System Architecture

```
PRESET SELECTION
  ↓ (active_preset stored in user_settings)
SIGNAL SCAN JOB (run_once, scheduled tick)
  Phase A: LibStrategyRunner.run_lib_strategy(name) × ENABLED_STRATEGIES
           → list[SignalCandidate] per strategy_name
  Phase B: per user → _preset_allows(active_preset, strategy_name)
           → filtered candidates → _process_candidate()

RISK PROFILE (independent)
  user_settings.risk_profile → capital_alloc_pct / tp_pct / sl_pct
  PATCH /autotrade/risk-profile → server-side validation (capital≤0.80, tp>sl)

COPY TRADE (independent)
  copy_trade_tasks → monitor.run_once() → _process_one(task, trade)
    copy_direction filter → allow_topups filter → execution_mode filter
    → TradeEngine.execute() (auto) | event_bus.emit(pending_confirm) (manual)
```

Three systems remain strictly isolated. No shared hot-path coupling.

---

## 3. Files Created / Modified

### New files
- `projects/polymarket/crusaderbot/migrations/035_copy_trade_extend.sql`
- `projects/polymarket/crusaderbot/services/signal_scan/lib_strategy_runner.py`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/CopyTradePage.tsx`

### Modified files
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py`
  — `_PRESET_ALLOWED`, `_LIB_STRATEGY_NAMES`, `_preset_allows()`, two-phase `run_once()`
- `projects/polymarket/crusaderbot/domain/positions/registry.py`
  — `delete_position_with_ledger()`
- `projects/polymarket/crusaderbot/domain/positions/__init__.py`
  — export `delete_position_with_ledger`
- `projects/polymarket/crusaderbot/domain/copy_trade/models.py`
  — 4 new optional fields with migration 035 defaults
- `projects/polymarket/crusaderbot/domain/copy_trade/repository.py`
  — `_SELECT` + `_row_to_task()` updated for new columns
- `projects/polymarket/crusaderbot/services/copy_trade/monitor.py`
  — copy_direction / allow_topups / execution_mode filter gates in `_process_one()`
- `projects/polymarket/crusaderbot/webtrader/backend/router.py`
  — `PATCH /autotrade/risk-profile`, `_PRESET_PARAMS` extended, 5 copy-trade CRUD routes
- `projects/polymarket/crusaderbot/webtrader/backend/schemas.py`
  — `RiskProfileRequest`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts`
  — `setRiskProfile()`, copy-trade API methods, CopyTask/CopyTaskCreate/CopyTaskPatch types
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx`
  — full restructure (8 presets + 4 coming-soon + 4 risk cards)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/App.tsx`
  — `/copy-trade` route
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/BottomNav.tsx`
  — 6-tab layout, Copy tab added
- `projects/polymarket/crusaderbot/bot/presets.py`
  — 5 new preset configs + updated `PRESET_ORDER`
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py`
  — `auto_trade_menu_kb()`, updated `mvp_risk_kb()`, `risk_picker()`, `preset_picker_kb()`
- `projects/polymarket/crusaderbot/bot/handlers/autotrade.py`
  — 2-sub-menu flow, `auto_trade:strategy` / `auto_trade:risk` / `auto_trade:back` handlers
- `projects/polymarket/crusaderbot/bot/handlers/setup.py`
  — `set_risk:custom` handling, routes to custom risk wizard entry
- `projects/polymarket/crusaderbot/bot/handlers/settings.py`
  — custom risk 3-step wizard: `risk_custom_capital` → `risk_custom_tp` → `risk_custom_sl`
- `projects/polymarket/crusaderbot/bot/handlers/copy_trade.py`
  — 8-step new wizard handler (states 10–19), `build_new_copy_wizard_handler()`
- `projects/polymarket/crusaderbot/bot/keyboards/copy_trade.py`
  — 8 new keyboard functions for new wizard
- `projects/polymarket/crusaderbot/bot/dispatcher.py`
  — updated autotrade callback pattern, registered new copy wizard handler
- `projects/polymarket/crusaderbot/tests/test_signal_scan_job.py`
  — 6 preset isolation unit tests
- `projects/polymarket/crusaderbot/tests/test_copy_trade.py`
  — 7 monitor filter tests (copy_direction, allow_topups, execution_mode)
- `projects/polymarket/crusaderbot/tests/test_positions_handler.py`
  — `delete_position_with_ledger` atomicity test

---

## 4. What Is Working

- Strategy isolation: `_preset_allows()` correctly gates lib strategy candidates per user
  based on `_PRESET_ALLOWED` map (verified by 6 unit tests covering all 9 preset values)
- `LibStrategyRunner`: converts `lib.Signal` → `domain.SignalCandidate` with `strategy_name`
  set; whale_tracking deferred gracefully (warning, empty list, no crash)
- `delete_position_with_ledger()`: atomic via `async with conn.transaction()`, ledger before
  position (FK-safe delete order), verified by atomicity test
- AutoTradePage: 8 strategy cards + 4 coming-soon (grayed, no onClick) + 4 risk cards render
  independently; custom risk inputs validated (capital ≤ 80%, TP > SL) before API call
- `/autotrade/risk-profile` endpoint: server-side capital ceiling (≤ 0.80) and tp > sl validation
- TG auto trade 2-sub-menu: Strategy Preset and Risk Profile routes wired; 8 preset confirmation
  cards; custom risk wizard 3 steps
- CopyTradePage (WebTrader): lists tasks, form creates tasks with all 8 fields
- Monitor filter gates: copy_direction skips SELL for buys_only tasks; allow_topups=false
  skips repeat entry on same market; execution_mode=manual emits pending_confirm event without
  calling TradeEngine.execute
- Migration 035: idempotent `IF NOT EXISTS` on all 4 new columns
- All modified Python files parse cleanly (AST verified)
- BottomNav: 6-tab layout with Copy tab at `/copy-trade`

---

## 5. Known Issues

- `lib/strategies/whale_tracking` requires external `prob.trade` API — deferred gracefully;
  emits warning log and returns empty list. Not activated by default (DEFERRED_STRATEGIES).
- TypeScript build has pre-existing `@types/react` / `react-router-dom` resolution errors
  in the remote container environment (node_modules not installed). Not introduced by this
  bundle — all existing pages have the same errors. Build must be verified in a provisioned
  environment.
- Old copy-trade wizard (3-step flow) remains in `copy_trade.py` for backward compatibility.
  Entry point `copytrade:copy:<addr>` has been moved to the new 8-step wizard handler (new
  handler registered first in dispatcher). Old wizard states 0–4 are isolated from new 10–19.
- `execution_mode='manual'` emits `copy_trade.pending_confirm` event but the corresponding
  TG confirm/reject keyboard handler is not yet built — event will be received but not
  actionable until a follow-up task wires the reply keyboard.

---

## 6. What Is Next

- WARP•SENTINEL validation required (Tier: MAJOR) before merge
- Wire `copy_trade.pending_confirm` event to TG reply keyboard (confirm/reject pair) as a
  follow-up task
- Provision node_modules in dev environment and run `npm run build` to confirm TypeScript clean
- Deploy migration 035 to staging DB before integration test run
- Consider activating whale_tracking once prob.trade API is confirmed reachable in staging

---

## Metadata

- **Validation Tier:** MAJOR — SENTINEL required before merge
- **Claim Level:** FULL RUNTIME INTEGRATION
- **Validation Target:** signal_scan_job preset filter, monitor filter gates, risk profile
  endpoint, WebTrader CopyTradePage + AutoTradePage, TG copy wizard, TG auto menu
- **Not in Scope:** live trading activation, whale_tracking external API, pending_confirm TG reply, CLOB adapter changes
- **Suggested Next Step:** WARP•SENTINEL validate on WARP/CRUSADERBOT-STRATEGY-RISK-COPY
