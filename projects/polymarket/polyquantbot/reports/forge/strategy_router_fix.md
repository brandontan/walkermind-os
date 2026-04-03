# FORGE-X REPORT — Strategy Router Fix (Telegram Toggle + Signal Integration)

---

## 1. What Was Built

Implemented a complete strategy toggle system for Polymarket trading bot:

- **StrategyStateManager** — in-memory strategy toggle state with Redis persistence and memory fallback
- **Telegram callback routing fix** — `strategy_toggle:{name}` dispatch handler eliminates "Unknown action"
- **Dynamic strategy UI** — `build_strategy_menu` now renders per-strategy ✅/⬜ checkbox state
- **Signal engine integration** — `generate_signals` accepts `strategy_state` dict and applies per-strategy p_model adjustments with `strategy_used_in_signal` logging
- **Fallback protection** — auto-enables all strategies when the last active strategy is disabled

---

## 2. Current System Architecture

```
Telegram User
    │ presses strategy toggle button
    ▼
CallbackRouter.route()
    │ callback_data: "action:strategy_toggle:ev_momentum"
    │ strips ACTION_PREFIX → action = "strategy_toggle:ev_momentum"
    ▼
_dispatch() → action.startswith("strategy_toggle:")
    │ parse strategy_name = "ev_momentum"
    │ StrategyStateManager.toggle("ev_momentum")
    ▼
handle_settings_strategy(strategy_state=mgr)
    │ renders updated UI with ✅/⬜ per strategy
    ▼
editMessageText → user sees updated strategy panel

Signal Pipeline
    │ StrategyState { ev_momentum: bool, mean_reversion: bool, liquidity_edge: bool }
    ▼
generate_signals(markets, strategy_state=state)
    │ if ev_momentum=False → p_model = p_market (no momentum edge)
    │ if mean_reversion=True → p_model pulled toward 0.5
    │ if liquidity_edge=True → p_model edge scaled by log-liquidity factor
    │ logs strategy_used_in_signal per market
    ▼
SignalResult list (only for markets passing all filters)
```

---

## 3. Files Created / Modified

### Created
- `strategy/strategy_manager.py` — StrategyStateManager class

### Modified
- `telegram/ui/keyboard.py` — `build_strategy_menu` adds `active_states` param; callback format changed from `strategy_toggle_{name}` to `strategy_toggle:{name}` (colon separator for unambiguous parsing)
- `telegram/handlers/settings.py` — `handle_settings_strategy` gains `strategy_state` parameter; renders full toggle UI when provided
- `telegram/handlers/callback_router.py` — adds `strategy_state` constructor param and `strategy_toggle:` dispatch handler
- `core/signal/signal_engine.py` — `generate_signals` gains `strategy_state` parameter with per-strategy p_model adjustments and `strategy_used_in_signal` logging
- `tests/test_telegram_callback_router.py` — CB-09 test updated to assert new colon-separator callback format

---

## 4. What's Working

- Strategy toggle via Telegram: user taps button → state toggles → UI refreshes with correct ✅/⬜
- No more "Unknown action" for strategy toggle callbacks
- UI dynamically reflects multi-strategy boolean state
- Fallback: disabling last active strategy auto-enables all (prevents zero alpha)
- Redis persistence: `load()` / `save()` with 3s timeout and memory fallback
- Signal engine: `strategy_used_in_signal` log event on every market tick when `strategy_state` is provided
- Invalid strategy toggle: logs warning, returns informative message (not crash)
- All 75 Telegram callback router tests pass

---

## 5. Known Issues

- `CallbackRouter` in `main.py` is not yet wired with `StrategyStateManager` (no instantiation in main). Caller must pass `strategy_state=StrategyStateManager()` when constructing `CallbackRouter`.
- Redis persistence is only invoked when the caller explicitly calls `await manager.save(redis)` — no automatic save on toggle yet (by design, keeps the toggle fast and non-blocking).
- `generate_signals` `strategy_state` parameter is additive — callers must pass it explicitly. Not yet injected from `StrategyStateManager` automatically in the trading loop.

---

## 6. What's Next

- Wire `StrategyStateManager` into `main.py` `CallbackRouter` construction
- Auto-save strategy state to Redis after each toggle (fire-and-forget task)
- Load strategy state on startup in `main.py` boot sequence
- Inject `strategy_state` into `generate_signals` calls in `trading_loop.py` / `live_paper_runner.py`
- Add Sentinel tests for strategy toggle end-to-end flow
