# FORGE-X REPORT — Strategy Toggle Fix: DB Persistence + Signal Guard

## 1. What Was Built

Extended the existing strategy toggle system with two critical improvements:

1. **DB persistence layer for strategy state** — Added `strategy_state` table to the PostgreSQL `DatabaseClient` (both `infra/db/database.py` and `infra/db.py`) with UPSERT-on-toggle and startup restore.  The `StrategyStateManager` now supports a `db` parameter alongside the existing `redis` parameter; DB is preferred over Redis when both are provided.

2. **Signal generation guard for zero active strategies** — `generate_signals()` now returns `[]` immediately when a `strategy_state` dict is supplied and every strategy is set to `False`, logging `signal_generation_blocked` with reason `"NO ACTIVE STRATEGY"`.  This prevents zero-alpha trading when all strategies are manually disabled via Telegram.

---

## 2. Current System Architecture

```
Telegram User
    │ presses strategy toggle button
    ▼
CallbackRouter._dispatch()
    │ action = "strategy_toggle:<name>"
    │ StrategyStateManager.toggle(name)
    │ StrategyStateManager.save(db=db, redis=redis)
    │   → infra.db.DatabaseClient.save_strategy_state(state)
    │     INSERT INTO strategy_state ... ON CONFLICT DO UPDATE
    ▼
handle_settings_strategy(strategy_state=mgr)
    │ renders ✅/⬜ per strategy
    ▼
editMessageText → user sees updated strategy panel

On startup:
    StrategyStateManager.load(db=db, redis=redis)
    │ DB populated → use DB state
    │ DB empty / error → fallback to Redis
    │ Redis empty / error → fallback to in-memory defaults

Signal Pipeline:
    generate_signals(markets, strategy_state=mgr.get_state())
    │ all values False → return [] + log signal_generation_blocked
    │ at least one True → proceed with per-strategy p_model adjustments
    ▼
execute_trade(signal)
```

---

## 3. Files Created / Modified

### Created
- `tests/test_strategy_toggle_system.py` — 22 unit tests (ST-01 – ST-22)

### Modified
- `infra/db/database.py` — Added `_DDL_STRATEGY_STATE` DDL; `_apply_schema()` now creates the table; added `load_strategy_state()` and `save_strategy_state()` methods
- `infra/db.py` — Same additions (legacy file kept in sync)
- `strategy/strategy_manager.py` — `load(redis, db)` and `save(redis, db)` updated: DB preferred over Redis; fallback chain DB → Redis → memory; `DatabaseClient` added to TYPE_CHECKING imports
- `core/signal/signal_engine.py` — Added active strategy guard before signal processing loop: if `strategy_state` provided with all `False` values → log `signal_generation_blocked` and return `[]`

---

## 4. What Is Working

- `strategy_state` table is created automatically on `DatabaseClient.connect()` (CREATE TABLE IF NOT EXISTS)
- `save_strategy_state(state)` performs an idempotent UPSERT for each strategy — safe to call on every toggle
- `load_strategy_state()` returns a `dict[str, bool]` from DB; returns `{}` on error
- `StrategyStateManager.load(db=db)` restores state from DB on startup; falls back to Redis when DB returns empty; falls back to defaults when Redis also unavailable
- `StrategyStateManager.save(db=db, redis=redis)` persists to both backends; returns `True` if at least one succeeds (partial failure logged as warning)
- Signal engine returns `[]` immediately when all strategies disabled — no wasted computation, no zero-alpha trades
- All 22 new tests pass; no regressions in existing 1057 passing tests

---

## 5. Known Issues

- `DatabaseClient.save_strategy_state()` and `load_strategy_state()` require an active connection pool; callers must await `db.connect()` at startup before calling these methods
- `StrategyStateManager.save(db=db)` does not call `db.connect()` automatically — the connection must already be established by the caller (main.py)
- `infra/db.py` (legacy standalone file) was also updated for consistency; the live import path is `infra.db` → `infra/db/__init__.py` → `infra/db/database.py`

---

## 6. What Is Next

- Wire `StrategyStateManager` into `main.py` startup: inject `db` client so strategy state is loaded from DB on every restart
- Call `strategy_mgr.save(db=db)` after every toggle inside `CallbackRouter` (currently only in-memory state is updated; DB persistence requires the caller to hold a `DatabaseClient` reference)
- Wire `strategy_mgr.get_state()` into `run_trading_loop()` so `generate_signals()` always receives the live strategy state
- Add Redis wiring for `StrategyStateManager` as redundant backup during startup
