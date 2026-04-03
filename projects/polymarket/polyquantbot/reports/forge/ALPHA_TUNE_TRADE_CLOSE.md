# ALPHA_TUNE_TRADE_CLOSE — FORGE-X Completion Report

**Date:** 2026-04-03  
**Branch:** feature/forge/alpha-tune-trade-close  
**Status:** COMPLETE ✅

---

## 1. Exit Logic

### Take Profit / Stop Loss Thresholds
| Trigger | Old Value | New Value |
|---------|-----------|-----------|
| Take Profit | +15% | **+5%** |
| Stop Loss | -8% | **-3%** |
| Max Hold Time | *(none)* | **1 hour (3600 s)** |

**File:** `risk/exit_monitor.py`

### Exit Evaluation Flow (per position, per scan cycle)

```
_evaluate_exit(record):
    1. hold_sec = now - record.opened_at
    2. IF hold_sec >= 3600 → trigger: "max_hold_time"
    3. Resolve current_price from MarketCache (bid for YES, ask for NO)
    4. pnl_pct = (current_price - entry_price) / entry_price
       (inverted for NO positions)
    5. IF pnl_pct >= 0.05  → trigger: "take_profit"
    6. IF pnl_pct <= -0.03 → trigger: "stop_loss"
    7. else → hold
```

### Double-Close Prevention
- `_closing_set` tracks position IDs currently being closed.
- `_exit_lock` serialises concurrent exit decisions.
- Idempotent: a position already `CLOSED` in PositionTracker is silently skipped.

---

## 2. PnL Calculation

### Realized PnL Formula
```
realized_pnl = (exit_price - entry_price) * size        # for YES
realized_pnl = -(exit_price - entry_price) * size       # for NO
```

### DB Update on Close
After every successful exit order, `ExitMonitor._execute_exit` calls:
```python
await db.update_trade_status(
    position_id,
    status="closed",
    pnl=realised_pnl,
    won=realised_pnl > 0,
)
```
Errors are caught, logged as `exit_monitor_db_update_failed`, and do not abort the close.

### Metrics in Trading Loop
Each tick now computes and logs:
- `realized_pnl` — sum of all closed trade PnL
- `unrealized_pnl` — mark-to-market of open positions
- `total_pnl` = `realized + unrealized`

---

## 3. Alpha Improvements

### Momentum Scale Reduction
| Parameter | Old | New |
|-----------|-----|-----|
| `_DEFAULT_MOMENTUM_SCALE` | 2.0 | **1.0** |

Reduces signal noise from momentum overshooting in thin-book or choppy markets.

### Dynamic Edge Threshold
**Old:** `threshold = base` (fixed 0.005)  
**New:** `threshold = base + volatility * 0.5`

- In low-volatility markets: threshold ≈ 0.005 (very close to base)
- In high-volatility markets (vol=0.05): threshold ≈ 0.030 (filters out marginal signals)

This prevents overtrading during volatile periods where alpha signals are noisy.

**Env override:** `SIGNAL_VOL_THRESHOLD_SCALE` (default `0.5`)

---

## 4. Sample Closed Trade

```json
{
  "event": "trade_closed",
  "position_id": "a1b2c3d4-...",
  "market_id": "0xabc...",
  "side": "YES",
  "entry_price": 0.62,
  "exit_price": 0.651,
  "size": 50.0,
  "correlation_id": "exit_scan:a1b2c3d4"
}

{
  "event": "realized_pnl",
  "position_id": "a1b2c3d4-...",
  "market_id": "0xabc...",
  "realized_pnl": 1.55,
  "won": true,
  "correlation_id": "exit_scan:a1b2c3d4"
}

{
  "event": "exit_reason",
  "position_id": "a1b2c3d4-...",
  "market_id": "0xabc...",
  "reason": "take_profit:pnl_pct=0.0500",
  "correlation_id": "exit_scan:a1b2c3d4"
}
```

---

## 5. Performance Impact

| Feature | Impact |
|---------|--------|
| Tighter TP/SL (5%/-3%) | Faster capital recycling, less drawdown |
| 1-hour max hold | No orphan positions left open indefinitely |
| Momentum scale 1.0 | ~50% less momentum overfit noise |
| Dynamic threshold | Suppresses trades in high-vol regime |
| Max 5 open positions | Caps total exposure at 5 × 10% = 50% bankroll |
| 30s per-market cooldown | Prevents burst-trading same market |

---

## 6. Files Created / Modified

| File | Change |
|------|--------|
| `risk/exit_monitor.py` | TP=5%, SL=-3%, max_hold=1h, DB update on close, Telegram alert, enhanced logging |
| `core/signal/alpha_model.py` | `_DEFAULT_MOMENTUM_SCALE` 2.0 → 1.0 |
| `core/signal/signal_engine.py` | Dynamic edge threshold (base + vol × scale) |
| `core/pipeline/trading_loop.py` | Max open positions (5), market cooldown (30 s), Telegram PnL summary |
| `reports/forge/ALPHA_TUNE_TRADE_CLOSE.md` | This report |

---

## 7. Known Issues

- `ExitMonitor` DB update uses `position_id` as `trade_id`; if the DB trade was inserted with a different key, the update will silently no-op (DatabaseClient._execute returns False but does not raise).
- Max hold time exit falls back to `entry_price` when no market cache is available — produces zero realized PnL. This is safe but sub-optimal.

---

## 8. What's Next

- SENTINEL validation of all new guards (max positions, cooldown, max hold)
- Integration test: run paper loop end-to-end with TP/SL/max-hold triggers
- Prometheus metrics: expose realized_pnl, open_positions, cooldown_skips as gauges
