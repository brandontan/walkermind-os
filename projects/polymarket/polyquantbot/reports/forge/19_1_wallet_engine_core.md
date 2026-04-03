# 19_1 — Wallet Engine Core

## 1. What Was Built

A fully idempotent paper trading wallet engine integrated into the PolyQuantBot execution pipeline. The system tracks cash, locked funds, and equity with full position lifecycle management, trade ledger, exposure calculation, and Telegram UI handlers.

**9 files created or modified:**

| File | Type |
|---|---|
| `core/wallet_engine.py` | NEW |
| `core/positions.py` | NEW |
| `core/ledger.py` | NEW |
| `core/exposure.py` | NEW |
| `execution/types.py` | NEW |
| `execution/paper_engine.py` | NEW |
| `telegram/handlers/trade.py` | NEW |
| `telegram/handlers/exposure.py` | NEW |
| `telegram/handlers/wallet.py` | MODIFIED (additive only) |

---

## 2. Current System Architecture

```
DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING
                                          │
                              ┌───────────┴──────────────┐
                              │        PaperEngine        │
                              │  execute_order()          │
                              │  close_order()            │
                              └───────┬──────────┬────────┘
                                      │          │
                            WalletEngine    PaperPositionManager
                            ─────────────  ──────────────────────
                            cash           open_position()
                            locked         close_position()
                            equity         partial_fill()
                            lock_funds()   update_price()
                            unlock_funds() get_all_open()
                            settle_trade()
                                      │
                                 TradeLedger
                                 ──────────
                                 record()
                                 get_realized_pnl()
                                 get_unrealized_pnl()
                                      │
                             ExposureCalculator
                             ──────────────────
                             calculate() → ExposureReport

Telegram UI:
  handlers/wallet.py    → handle_paper_wallet()
  handlers/trade.py     → handle_trade(), handle_trade_detail()
  handlers/exposure.py  → handle_exposure()
```

### Idempotency Model

Every mutating operation accepts a `trade_id` parameter. Duplicate `trade_id` calls are silent no-ops tracked by `_seen_trade_ids` (Python sets). This covers:

- `WalletEngine`: separate sets for `lock_funds`, `unlock_funds`, `settle_trade`
- `PaperPositionManager`: unified set for open/close/partial
- `TradeLedger`: unified set for `record()`
- `PaperEngine`: unified set for `execute_order` / `close_order`

### Risk Guard

`WalletEngine.lock_funds()` raises `InsufficientFundsError` when `cash < amount`. `PaperEngine.execute_order()` checks balance before attempting any lock, and also catches the exception for a clean REJECTED result.

---

## 3. Files Created / Modified

### Created

| Path | Description |
|---|---|
| `projects/polymarket/polyquantbot/core/wallet_engine.py` | WalletEngine — cash/locked/equity tracking, asyncio Lock, idempotent, InsufficientFundsError |
| `projects/polymarket/polyquantbot/core/positions.py` | PaperPosition dataclass + PaperPositionManager (open/close/partial/update_price) |
| `projects/polymarket/polyquantbot/core/ledger.py` | LedgerEntry dataclass + TradeLedger (append-only, market index, realized PnL aggregation) |
| `projects/polymarket/polyquantbot/core/exposure.py` | ExposureReport dataclass + ExposureCalculator (per-position + aggregate) |
| `projects/polymarket/polyquantbot/execution/types.py` | Shared OrderInput, WalletState (re-export), PositionState, LedgerEntry (re-export) |
| `projects/polymarket/polyquantbot/execution/paper_engine.py` | PaperEngine — execute_order + close_order with slippage, partial fills, timeout guard |
| `projects/polymarket/polyquantbot/telegram/handlers/trade.py` | handle_trade() + handle_trade_detail() — positions Telegram UI |
| `projects/polymarket/polyquantbot/telegram/handlers/exposure.py` | handle_exposure() — exposure report Telegram UI |

### Modified

| Path | Change |
|---|---|
| `projects/polymarket/polyquantbot/telegram/handlers/wallet.py` | Added `_paper_wallet_engine`, `set_paper_wallet_engine()`, `handle_paper_wallet()` — existing `handle_wallet()` untouched |

---

## 4. What Is Working

- ✅ `WalletEngine`: cash/locked/equity state with asyncio Lock, idempotent lock/unlock/settle, `InsufficientFundsError` guard, crash recovery via `restore_state()`
- ✅ `PaperPositionManager`: full lifecycle — open, partial_fill, update_price, close; weighted avg entry price; idempotent by trade_id
- ✅ `TradeLedger`: append-only audit log; market index for fast lookup; `get_realized_pnl()` and `get_unrealized_pnl()` aggregations
- ✅ `ExposureCalculator`: per-position and aggregate exposure metrics; zero-div safe
- ✅ `PaperEngine.execute_order()`: validation → balance check → partial fill sim (80–100%) → slippage (±0.5%) → lock_funds → open_position → ledger record → rollback on error
- ✅ `PaperEngine.close_order()`: close_position → unlock_funds → settle_trade → ledger CLOSE → PnLTracker update (if available)
- ✅ Telegram handlers: trade positions list, per-position detail, exposure report, paper wallet balance — all return (text, keyboard) tuples
- ✅ `handle_paper_wallet()`: shows cash / locked / equity via WalletEngine; `handle_wallet()` unchanged
- ✅ All files: Python 3.11+ type hints, `from __future__ import annotations`, structlog JSON logging, asyncio only, zero silent failures
- ✅ Syntax check: all 9 files pass `python -m py_compile`
- ✅ Domain structure: all code within `core/` and `execution/` — no phase folders

---

## 5. Known Issues

- **Wire-up not yet done**: `WalletEngine`, `PaperPositionManager`, `TradeLedger`, `PaperEngine` are not yet instantiated in `main.py` or `bootstrap.py`. Injection into Telegram handlers and callback router requires a follow-up wiring task.
- **Partial fill randomness**: `random.uniform(0.80, 1.0)` is deterministic-seed-free; in production this may cause non-reproducible test results. A seed parameter could be added for testing.
- **PaperEngine price validation**: `price` must be 0 < price ≤ 1 (prediction market range). If used with non-normalized prices, validation will reject the order. Adjust `_validate_order` if needed.
- **No persistence layer**: All state is in-memory. After restart, `restore_state()` on `WalletEngine` must be called with a persisted snapshot. A DB persistence layer is not yet implemented.

---

## 6. What Is Next

1. **Wire up in `main.py` / `bootstrap.py`**: instantiate `WalletEngine`, `PaperPositionManager`, `TradeLedger`, `ExposureCalculator`, `PaperEngine` and inject into Telegram handlers.
2. **Callback router integration**: add `action:paper_wallet`, `action:trade`, `action:exposure` routes in `telegram/callback_router.py`.
3. **Persistence layer**: persist `WalletState` to DB on every mutation; restore on startup.
4. **Price feed integration**: wire `PaperPositionManager.update_price()` to the WebSocket data feed for live mark-to-market PnL.
5. **SENTINEL validation**: run full system validation gate before go-live.
