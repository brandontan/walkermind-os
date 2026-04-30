# PNL_ALPHA_ENGINE — FORGE-X Completion Report

**Date:** 2026-04-03  
**Branch:** `feature/forge/pnl-alpha-engine`  
**Status:** ✅ COMPLETE

---

## 1. What Was Built

### Part 1 — PnL System

- **Extended `trades` table** (`infra/db.py`) with `user_id`, `status`, and `entry_price` columns (backward-compatible; migration adds columns to existing tables).
- **New `positions` table** (`infra/db.py`): tracks open positions per `(user_id, market_id)` with `avg_price` and `size`.
- **New `DatabaseClient` methods**: `upsert_position()`, `get_positions()`, `update_trade_status()` — all fail-safe with retry.
- **`monitoring/pnl_calculator.py`**: Stateless `PnLCalculator` with three static methods:
  - `calculate_realized_pnl(trades)` — sum of settled PnL.
  - `calculate_unrealized_pnl(positions, current_prices)` — mark-to-market estimate.
  - `calculate_metrics(trades)` — `total_pnl`, `win_rate`, `drawdown`, `total_trades`, `wins`, `losses`.
- **Telegram `📊 Performance` button** restored in the status sub-menu (inline UI) routed to the existing `/performance` command handler which shows PnL, win rate, and trades count.

### Part 2 — Real Alpha Model

- **`core/signal/alpha_model.py`**: New `ProbabilisticAlphaModel` class.
  - Maintains per-market rolling price history (`deque` with configurable window, default 20 ticks).
  - `record_tick(market_id, price)` — feeds a price observation into the buffer.
  - `compute_p_model(market_id, p_market, liquidity_usd)` — returns `(p_model, volatility)` using:
    - **Price deviation**: distance of current price from rolling mean (mean-reversion signal).
    - **Momentum**: mean signed price change over the window (trend signal).
    - **Liquidity weighting**: scales momentum contribution by `min(liquidity / ref_liquidity, 1.0)` — thin books produce noisier signals.
  - Volatility = sample standard deviation of the price series (floor: `1e-4`).

- **`core/signal/signal_engine.py`** — `random.uniform` removed, real alpha integrated:
  - `import random` deleted.
  - `_EDGE_THRESHOLD` raised from `0.01` (TEMP level) back to `0.02` (production level).
  - Optional `alpha_model` parameter added to `generate_signals()` — when provided, overrides the `p_model` field with the model's computed value.
  - When `alpha_model` is absent, `p_model` is read directly from the market dict (caller-supplied external model).
  - **Confidence score** `S = edge / volatility` computed for every signal candidate.
  - **Dual signal filter**: `edge > threshold` **AND** `S > min_confidence` (default `0.5`, configurable via `SIGNAL_MIN_CONFIDENCE` env var or function param).
  - All signal decisions logged: `signal_debug`, `signal_generated`, `trade_skipped` (with reason).

### Part 3 — Integration

- **Pipeline**: market context → `alpha_model.compute_p_model` (if wired) → `generate_signals` → edge+confidence filter → execution → PnL update.
- **Structured logging** added for every decision: `signal_debug`, `signal_generated`, `trade_skipped`, `pnl_realized_calculated`, `pnl_metrics_calculated`.

---

## 2. Current System Architecture

```
DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING
         │                                               │
         └──[alpha_model.py]──────────────────►[pnl_calculator.py]
              p_model + volatility           realized/unrealized PnL
```

New modules:

| File | Role |
|------|------|
| `core/signal/alpha_model.py` | Stateful probabilistic alpha model |
| `core/signal/signal_engine.py` | Real alpha, confidence score, dual filter |
| `monitoring/pnl_calculator.py` | PnL computation (stateless helpers) |
| `infra/db.py` | Extended schema: `positions` table + trades migration |

---

## 3. Files Created / Modified

### Created
- `core/signal/alpha_model.py` — `ProbabilisticAlphaModel`
- `monitoring/pnl_calculator.py` — `PnLCalculator`
- `reports/forge/PNL_ALPHA_ENGINE.md` — this report

### Modified
- `core/signal/signal_engine.py` — removed `random.uniform`; real alpha; confidence score; dual filter
- `infra/db.py` — `positions` DDL; trades migration; `upsert_position`, `get_positions`, `update_trade_status`
- `telegram/ui/keyboard.py` — `build_status_menu()` adds `📊 Performance` button
- `telegram/handlers/callback_router.py` — routes `action:performance`; removes `performance` from legacy hard block
- `tests/test_signal_execution_activation.py` — updated 8 tests (SE-02–06, SE-12–13) to reflect real alpha semantics
- `tests/test_telegram_callback_router.py` — updated CB-03 to expect `performance` in status menu

---

## 4. What's Working

- **Real alpha model** computes `p_model` from price deviation + momentum + liquidity. Verified with upward-momentum test: `p_model=0.55 > p_market=0.50` for 5-tick upward series.
- **Confidence score** correctly filters weak signals: `S = edge / volatility`.
- **PnL calculator** verified: `realized_pnl=22.0`, `win_rate=0.6`, `unrealized_pnl=7.5` on test data.
- **Database schema** extended with `positions` table and backward-compatible `trades` migration.
- **Telegram performance** button renders in status sub-menu; routes to `/performance` command.
- **32/32 signal+execution tests pass**, **75/75 callback router tests pass**.

---

## 5. Known Issues

- `ProbabilisticAlphaModel` not yet wired into `core/pipeline/trading_loop.py` (requires caller to instantiate and pass `alpha_model` to `generate_signals`).
- `upsert_position()` not yet called from the execution layer (wiring pending in trading loop).
- `PnLCalculator` not yet called after trade settlement (market resolution PnL update still pending per PROJECT_STATE roadmap).

---

## 6. What's Next

1. Wire `ProbabilisticAlphaModel` into `core/pipeline/trading_loop.py` so that every market tick updates the model before signal generation.
2. Wire `upsert_position` into `LiveExecutor` trade result callback.
3. Wire `PnLCalculator.calculate_metrics` into the monitoring metrics snapshot.
4. Market resolution PnL: update `TradeResult.pnl` when Polymarket settles a market.
5. Bayesian updater integration: pass posterior confidence as `ev_adjustment` into alpha model.
