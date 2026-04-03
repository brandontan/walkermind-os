# Phase 17.3 — Trade Visibility Metrics

**Date:** 2026-04-03
**Branch:** feature/forge/trade-visibility-metrics
**Status:** ✅ COMPLETE

---

## 1. What Was Built

Full trading visibility layer enabling performance metrics, open positions,
PnL summaries, and a fixed wallet handler with timeout + cached fallback.

Implemented the following Telegram inline handlers:
- `/performance` — aggregated win rate, trade count, PnL, drawdown
- `/positions` — all open positions with market question, side, avg price, size, unrealized PnL
- `/pnl` — realized PnL, unrealized PnL, and total PnL
- **Wallet fix** — 2 s timeout on every API call, 3× retry loop, cached balance fallback on failure

Also fixed `MultiStrategyMetrics` to gracefully accept an empty strategy list
(previously raised `ValueError`) and added aggregate helpers
(`total_pnl`, `overall_win_rate`, `aggregate_performance()`).

---

## 2. Current System Architecture

```
DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING
                                                         │
                                          telegram/handlers/
                                          ├── performance.py   ← NEW
                                          ├── positions.py     ← NEW
                                          ├── pnl.py           ← NEW
                                          ├── wallet.py        ← FIXED
                                          └── callback_router.py ← UPDATED

monitoring/multi_strategy_metrics.py        ← FIXED (empty list + aggregates)
telegram/ui/keyboard.py                     ← UPDATED (Positions + PnL buttons)
telegram/ui/screens.py                      ← UPDATED (positions_screen, pnl_screen)
main.py                                     ← UPDATED (wire handlers)
```

Services are injected via module-level `set_*` functions called from `main.py`
after each component is initialised, consistent with the existing wallet handler pattern.

---

## 3. Files Created / Modified

**Created:**
- `telegram/handlers/performance.py` — standalone performance handler; reads from `MultiStrategyMetrics` + `PnLTracker`
- `telegram/handlers/positions.py` — open positions handler; reads from `PositionManager` + `MarketMetadataCache` + `PnLTracker`
- `telegram/handlers/pnl.py` — PnL summary handler; reads from `PnLTracker`

**Modified:**
- `monitoring/multi_strategy_metrics.py` — allow empty `strategy_names` (warn not raise); add `total_pnl`, `overall_win_rate`, `aggregate_performance()` properties
- `telegram/handlers/wallet.py` — `_BALANCE_FETCH_TIMEOUT_S = 2.0`; `asyncio.wait_for` on every service call; `_cached_balance` + `_cached_address` module-level fallback; fallback displayed on retry exhaustion
- `telegram/handlers/callback_router.py` — replaced `cmd.handle("performance")` delegation with direct `handle_performance()`; added `positions` and `pnl` action routing
- `telegram/ui/keyboard.py` — `build_status_menu()` now has 3 rows: `[Positions][PnL]`, `[Performance][Refresh]`, `[Main Menu]`
- `telegram/ui/screens.py` — added `positions_screen(positions)` and `pnl_screen(realized, unrealized, total)`
- `main.py` — wires `multi_metrics`, `pnl_tracker`, `position_manager`, `market_cache` into all three new handlers via module-level injection after each service is created

---

## 4. What Is Working

- `MultiStrategyMetrics([])` no longer raises; logs warning and initialises to empty state ✅
- `MultiStrategyMetrics.aggregate_performance()` returns `{total_pnl, win_rate, total_trades, drawdown}` ✅
- `handle_performance(mode)` — returns formatted performance screen; safe when no strategies/trades ✅
- `handle_positions()` — returns "No open positions" when empty; lists positions with question/side/avg/size/upnl when populated ✅
- `handle_pnl()` — returns realized/unrealized/total PnL; returns zeros when no tracker ✅
- Wallet handler — all calls wrapped in 2 s `wait_for`; cached balance returned on timeout/retry exhaustion ✅
- `build_status_menu()` now includes `[Positions][PnL]` buttons in addition to `[Performance][Refresh]` ✅
- `positions_screen` and `pnl_screen` render correctly in Markdown ✅
- All 95 related tests pass (75 callback router + 20 monitoring) ✅

---

## 5. Known Issues

- `drawdown` in `aggregate_performance()` always returns `0.0` — MultiStrategyMetrics does not maintain a time-series equity curve; accurate drawdown requires the `PnLCalculator.calculate_metrics()` path over historical trade data from the database
- `handle_positions` unrealized PnL comes from `PnLTracker.get(market_id).unrealized`; this is only accurate if `record_unrealized()` is being called per-tick by `run_trading_loop()`

---

## 6. What Is Next

- Connect `PnLCalculator.calculate_metrics()` to database trade history for accurate per-period drawdown
- Add `/history` handler for closed trade log
- Wire Telegram wallet tests to cover new timeout/cached-balance paths
