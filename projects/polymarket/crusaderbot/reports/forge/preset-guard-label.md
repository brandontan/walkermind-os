# WARP•FORGE Report — preset-guard-label

**Branch:** WARP/ROOT-preset-guard-label
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** NULL preset safety guard + active_preset label display for late_entry_v3 trades
**Not in Scope:** live execution path, signal_following lib strategies, other preset types
**Suggested Next Step:** WARP🔹CMD review → merge → Fly redeploy

---

## 1. What Was Built

Two bugs fixed together:

**Bug 1 — Safety: NULL preset users could have trades opened**

Users with `active_preset = NULL` in `user_settings` (i.e. they enabled `auto_trade_on` but never selected a strategy preset) could still have trades fired via the `signal_following` fallback. `_preset_allows(None, lib_name)` fell back to `_LIB_STRATEGY_NAMES` and returned True for every lib strategy, so the bot silently traded for unconfigured accounts.

Fix: Early `continue` guard at the top of the per-user loop in `signal_scan_job.run_once` — any user with `active_preset IS NULL` is skipped with a structured WARNING log (`scan_skipped_no_preset`). A matching preset check gate was added to `POST /autotrade/toggle`: when `enabled=True`, if the user has no configured preset the endpoint returns HTTP 400 with `"select a strategy preset before enabling auto-trade"`.

**Bug 2 — Display: All late_entry_v3 trades showed "CLOSE SWEEP" in portfolio history**

All three candle presets (close_sweep / safe_close / flip_hunter) share `strategy_type = 'late_entry_v3'` in the DB. The frontend `STRATEGY_LABELS` dict hardcoded `late_entry_v3 → "Close Sweep"`, so safe_close and flip_hunter trades were mislabelled.

Fix: Added `active_preset` column to `positions` table (migration 062), threaded the value through the full execution chain (TradeSignal → engine → router → paper.execute → INSERT), exposed it in the API response (`PositionItem` schema + SELECT), and used it in the frontend via a new `PRESET_LABEL` map (`close_sweep → "Close Sweep"`, `safe_close → "Safe Close"`, `flip_hunter → "Flip Hunter"`). Old positions with `active_preset = NULL` fall back to `fmtStrategy(p.strategy_type)` unchanged.

---

## 2. Current System Architecture

```
signal_scan_job.run_once()
  └─ per-user loop
       ├─ [NEW] active_preset NULL guard → skip + WARNING
       └─ _build_trade_signal(row, ...)
            └─ TradeSignal(active_preset=row["active_preset"])  [NEW field]
                 └─ TradeEngine.execute()
                      └─ _router_execute(active_preset=signal.active_preset)  [NEW param]
                           └─ domain/execution/router.execute(active_preset=...)  [NEW param]
                                └─ paper_engine.execute(active_preset=...)  [NEW param]
                                     └─ INSERT INTO positions (..., active_preset)  [NEW col]

POST /autotrade/toggle
  └─ [NEW] if enabled: check active_preset in user_settings → 400 if NULL

GET /positions / GET /portfolio/positions
  └─ SELECT ... p.active_preset ...  [NEW col in query]
       └─ PositionItem(active_preset=r["active_preset"])  [NEW field in schema + api.ts]

PortfolioPage.tsx
  └─ strategyLabel = PRESET_LABEL[p.active_preset] ?? fmtStrategy(p.strategy_type)  [NEW]
```

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/migrations/062_positions_active_preset.sql`

**Modified:**
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py`
  - NULL preset `continue` guard in `run_once` per-user loop
  - `active_preset` passed from `row` in `_build_trade_signal` return
- `projects/polymarket/crusaderbot/services/trade_engine/engine.py`
  - `TradeSignal` dataclass: `active_preset: Optional[str] = None`
  - `_router_execute(active_preset=signal.active_preset)` call
- `projects/polymarket/crusaderbot/domain/execution/router.py`
  - `execute()` signature: `active_preset: str | None = None`
  - All 3 `_paper()` call sites pass `active_preset`
- `projects/polymarket/crusaderbot/domain/execution/paper.py`
  - `execute()` signature: `active_preset: str | None = None`
  - INSERT INTO positions now includes `active_preset` as `$11`
- `projects/polymarket/crusaderbot/webtrader/backend/schemas.py`
  - `PositionItem`: `active_preset: Optional[str] = None`
- `projects/polymarket/crusaderbot/webtrader/backend/router.py`
  - `POST /autotrade/toggle`: preset guard before enabling
  - `GET /positions` + `GET /portfolio/positions`: SELECT + constructor include `active_preset`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts`
  - `PositionItem`: `active_preset?: string | null`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx`
  - Added `PRESET_LABEL` map
  - `strategyLabel` uses `PRESET_LABEL[p.active_preset]` with fallback to `fmtStrategy`

---

## 4. What Is Working

- Migration 062 applied to Supabase production (confirmed via MCP execute_sql)
- `tsc --noEmit` clean
- NULL preset users skipped with structured WARNING — no trades fired for unconfigured accounts
- `/autotrade/toggle` returns 400 with clear message when no preset configured
- New trades will write `active_preset` to positions row on open
- `PortfolioPage` shows correct label: "Safe Close" for safe_close, "Flip Hunter" for flip_hunter, "Close Sweep" for close_sweep
- Existing positions with `active_preset = NULL` still display the strategy_type-derived label (no regression)

---

## 5. Known Issues

- Existing positions (before this deploy) will still show "Close Sweep" for safe_close and flip_hunter trades — `active_preset` was not backfilled; this is expected and acceptable (historical trades only)
- Live execution engine (`domain/execution/live.py`) not updated — `active_preset` not persisted for live orders; live is OFF and will need the same threading when activated

---

## 6. What Is Next

- WARP🔹CMD review → merge → Fly redeploy
- Post-deploy verify: new flip_hunter / safe_close positions show correct label in portfolio history
- Post-deploy verify: user with no preset configured cannot enable auto-trade (400 returned)
- Live execution path: add `active_preset` to `live.execute()` when live trading lane opens
