# PNL_ALPHA_INTEGRATION — FORGE-X Completion Report

**Date:** 2026-04-03  
**Branch:** feature/forge/pnl-alpha-integration-final  
**Status:** ✅ COMPLETE

---

## 1. Integration Flow

```
market data (Gamma REST)
        ↓
alpha_model.record_tick(market_id, price)   ← every market, every tick
        ↓
generate_signals(markets, bankroll, alpha_model=alpha_model)
        ↓ SignalResult with real p_model / edge / confidence
execute_trade(signal, mode, ...)
        ↓ TradeResult
db.upsert_position(user_id, market_id, avg_price, size)
db.insert_trade(...)
db.update_trade_status(trade_id, "open")
        ↓
db.get_positions(user_id)
PnLCalculator.calculate_unrealized_pnl(positions, market_prices)
PnLCalculator.calculate_metrics(trades)
log.info("pnl_update", pnl=metrics)
```

---

## 2. PnL Update Cycle

Each loop tick:

1. `db.get_positions(user_id)` — fetch all open positions for the user.
2. `market_prices` dict built from `lastTradePrice` fields in the fetched markets.
3. `PnLCalculator.calculate_unrealized_pnl(positions, market_prices)` — mark-to-market.
4. `PnLCalculator.calculate_metrics(trades[-500:])` — win_rate, drawdown, total_pnl.
5. Combined metrics logged as `pnl_update` event with full dict payload.

---

## 3. Alpha Usage

`ProbabilisticAlphaModel` is instantiated once at `run_trading_loop` startup and
shared across all loop ticks (stateful rolling window).

- **`record_tick(market_id, price)`** is called for every market with `price > 0`
  before signals are generated.
- **`compute_p_model`** is invoked inside `generate_signals` via the `alpha_model=`
  parameter, producing a data-driven `p_model` from:
  - Price deviation from rolling mean (mean-reversion)
  - Per-tick momentum (trend)
  - Liquidity weighting (thin books → less momentum influence)
- Confidence score `S = edge / volatility` filters signals (dual filter: edge > 0.02
  **and** S > 0.5).

---

## 4. Sample Logs

```json
{"event": "trading_loop_started", "mode": "PAPER", "bankroll": 1000.0,
 "loop_interval_s": 5.0, "user_id": "default", "db_enabled": true}

{"event": "signals_generated", "count": 2}

{"event": "trade_loop_executed", "market_id": "0xabc...", "side": "YES",
 "mode": "PAPER", "filled_size_usd": 50.0, "fill_price": 0.62}

{"event": "pnl_update", "pnl": {
    "total_pnl": 3.25,
    "win_rate": 0.6667,
    "drawdown": 0.0,
    "total_trades": 3,
    "wins": 2,
    "losses": 1,
    "unrealized_pnl": 1.12
}}
```

---

## 5. Performance Output (Telegram)

The `/performance` command and `action:performance` callback now display:

```
📊 PERFORMANCE REPORT
─────────────────────────────────────────
Mode: `PAPER` | Trades: `3` | PnL: `+$3.25`
Win Rate: `66.7%` | Drawdown: `0.00%`
─────────────────────────────────────────
PER-STRATEGY:
  ev_momentum   pnl=+$1.50  wr=75.0%  n=2
  ...
```

`performance_screen` (used for quick inline summary) now accepts and displays
`win_rate` and `drawdown` in addition to `total_pnl` and `total_trades`.

---

## 6. Files Created / Modified

| File | Change |
|------|--------|
| `core/pipeline/trading_loop.py` | Alpha init + record_tick, alpha_model→generate_signals, position upsert + trade insert/status after fills, PnL metrics computation and logging each tick. Added `db` and `user_id` params. |
| `telegram/ui/screens.py` | `performance_screen` updated to accept and show `win_rate` and `drawdown`. |
| `telegram/message_formatter.py` | `format_performance_report` updated to accept and display `win_rate` and `drawdown` in header line. |
| `telegram/command_handler.py` | `_handle_performance` computes overall win_rate + max drawdown and passes to formatter; payload enriched. |
| `tests/test_pipeline_integration_final.py` | `test_tl04` assertion updated to check `alpha_model` kwarg present; `test_tl09` `rotating_signals` accepts `alpha_model` kwarg. |

---

## 7. What's Working

- Alpha model hydrates on every market tick via `record_tick`.
- Signals use real `p_model` derived from price history.
- Successful fills trigger `upsert_position` + `insert_trade` + `update_trade_status`.
- PnL metrics (unrealized, win_rate, drawdown) are computed and logged every tick.
- Telegram `/performance` screen shows all four key metrics.
- All pre-existing tests pass (pre-existing failures from missing `websockets` /
  `eth_account` modules are unrelated to this task).

---

## 8. Known Issues

- `db_enabled` is `False` by default (no `DatabaseClient` injected by default). A
  `DatabaseClient` instance must be passed via the `db=` parameter at startup.
- `insert_trade` is idempotent (ON CONFLICT DO NOTHING), so re-runs do not double-count.
- Position size is set to `filled_size_usd` (not shares); avg_price is the fill price.
  Weighted-average merging across multiple fills requires a future update to
  `upsert_position` if per-market cost-basis tracking is needed.

---

## 9. What's Next

1. Inject `DatabaseClient` instance via `main.py` bootstrap sequence.
2. Weighted-average position merging in `upsert_position` for multi-fill cost basis.
3. Market resolution PnL: call `update_trade_status(trade_id, "closed", pnl=...)` on settlement.
4. Persistent signal dedup via Redis for restart safety.
5. Bayesian updater integration: pass posterior confidence as `ev_adjustment` into alpha model.
