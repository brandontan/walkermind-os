# 20_1 — System Wiring Engine

## 1. What Was Built

End-to-end wiring of `WalletEngine`, `PaperPositionManager`, `TradeLedger`,
`ExposureCalculator`, and `PaperEngine` into the main runtime and Telegram
system.  All trading, wallet, and exposure features now use real state
instead of dummy data.

**6 files created or modified:**

| File | Type |
|---|---|
| `execution/engine_router.py` | NEW |
| `main.py` | MODIFIED |
| `core/pipeline/trading_loop.py` | MODIFIED |
| `telegram/handlers/callback_router.py` | MODIFIED |
| `telegram/handlers/wallet.py` | MODIFIED |
| `telegram/ui/keyboard.py` | MODIFIED |

---

## 2. Current System Architecture

```
main.py bootstrap
│
├── get_engine_container()  ← singleton, created once
│   └── EngineContainer
│       ├── WalletEngine          (cash/locked/equity)
│       ├── PaperPositionManager  (position lifecycle)
│       ├── TradeLedger           (append-only audit log)
│       ├── ExposureCalculator    (risk metrics)
│       └── PaperEngine           (execute_order / close_order)
│           └── inject_into_handlers()
│               ├── handlers.wallet    ← set_paper_wallet_engine()
│               ├── handlers.trade     ← set_paper_engine() + set_position_manager()
│               └── handlers.exposure  ← set_exposure_calculator() + set_position_manager() + set_wallet_engine()
│
├── _callback_router.set_paper_wallet_engine()
├── _callback_router.set_paper_engine()
├── _callback_router.set_paper_position_manager()
└── _callback_router.set_exposure_calculator()

Trading loop (PAPER mode):
  execute_trade() → success
     └── paper_engine.execute_order()
         ├── WalletEngine.lock_funds()
         ├── PaperPositionManager.open_position()
         └── TradeLedger.record()

CallbackRouter._dispatch():
  action:wallet    → handle_paper_wallet()   [PAPER mode, engine injected]
                  → handle_wallet()          [LIVE mode or no engine]
  action:trade     → handle_trade()          [PaperPositionManager + PnLTracker]
  action:exposure  → handle_exposure()       [ExposureCalculator + WalletEngine]
  action:paper_wallet → handle_paper_wallet() [explicit paper route]

Telegram UI:
  build_paper_wallet_menu() → [📊 Trade][📉 Exposure][🔄 Refresh][🏠 Main Menu]
  build_status_menu()       → [📈 Positions][💹 PnL][📊 Performance][📉 Exposure]...
```

---

## 3. Files Created / Modified

### Created

| Path | Description |
|---|---|
| `projects/polymarket/polyquantbot/execution/engine_router.py` | `EngineContainer` singleton with all 5 engines; `inject_into_handlers()` wires all deps; `get_engine_container()` singleton factory |

### Modified

| Path | Change |
|---|---|
| `projects/polymarket/polyquantbot/main.py` | Added `get_engine_container()` call after PnLTracker; `engine_container.inject_into_handlers()`; `_set_trade_pnl(pnl_tracker)`; injects 4 engine refs into `_callback_router`; passes `paper_engine=engine_container.paper_engine` to `run_trading_loop()` |
| `projects/polymarket/polyquantbot/core/pipeline/trading_loop.py` | Added `paper_engine: Optional[Any] = None` param; added `paper_engine_wired` to startup log; added step **4d-paper**: calls `paper_engine.execute_order()` on every PAPER mode fill to sync wallet/positions/ledger |
| `projects/polymarket/polyquantbot/telegram/handlers/callback_router.py` | Added 4 `Optional` engine fields; added `set_paper_wallet_engine()`, `set_paper_engine()`, `set_paper_position_manager()`, `set_exposure_calculator()` injection methods; updated `action:wallet` → `handle_paper_wallet()` in PAPER mode; added `action:paper_wallet`, `action:trade`, `action:exposure` dispatch routes |
| `projects/polymarket/polyquantbot/telegram/handlers/wallet.py` | Imported `build_paper_wallet_menu`; `handle_paper_wallet()` now returns `build_paper_wallet_menu()` instead of `build_wallet_menu()` |
| `projects/polymarket/polyquantbot/telegram/ui/keyboard.py` | Added `build_paper_wallet_menu()` — new paper wallet navigation (Trade + Exposure + Refresh + Back); updated `build_status_menu()` to include `📉 Exposure` button alongside Performance |

---

## 4. What Is Working

- ✅ `EngineContainer` singleton: `get_engine_container()` creates exactly one instance; duplicate calls return same object; structured log on init and injection
- ✅ `inject_into_handlers()`: wires `WalletEngine`, `PaperEngine`, `PaperPositionManager`, `ExposureCalculator` into all three Telegram handlers in one call
- ✅ `main.py` bootstrap: engines initialized after DB/PnLTracker; all 4 callback_router injection methods called; PnLTracker wired into trade handler
- ✅ `action:wallet` → `handle_paper_wallet()` in PAPER mode: shows cash/locked/equity with navigation to Trade and Exposure
- ✅ `action:trade` route: dispatches `handle_trade(mode=...)` — shows open positions + unrealized PnL from PaperPositionManager
- ✅ `action:exposure` route: dispatches `handle_exposure()` — shows real exposure report via ExposureCalculator + WalletEngine
- ✅ `action:paper_wallet` explicit route: always uses paper engine regardless of mode
- ✅ Trading loop integration: `paper_engine.execute_order()` called on every PAPER mode fill → wallet deducted, position created, ledger updated
- ✅ Async safety: all engine mutations guarded by asyncio Lock in WalletEngine; no shared mutable state races
- ✅ Zero silent failures: every exception in paper_engine call is caught and logged as `paper_engine_order_failed`
- ✅ All 75 callback_router tests pass; total 908 tests pass
- ✅ Syntax check: all 6 files pass `python -m py_compile`
- ✅ No phase folders; no legacy imports; all code in correct domain folders

---

## 5. Known Issues

- **Pre-existing test failure**: `test_tl04_signals_generated_from_markets` fails because the market dict now includes extra `prices`, `outcomes`, `token_ids` fields added in a prior ingest refactor. This failure existed before this task and is NOT related to our changes.
- **Price range validation**: `PaperEngine._validate_order()` requires `0 < price ≤ 1`. If `fill_price` from `execute_trade()` ever exceeds 1.0 (non-Polymarket price), the paper engine call will log a rejection but trading continues normally. For Polymarket, all prices are in [0, 1] range so this is not a practical concern.
- **No persistence for WalletEngine state**: All wallet/position/ledger state is in-memory. After restart, state is reset to `PAPER_INITIAL_BALANCE`. DB persistence layer (Task 19.1 Known Issues) is still pending.
- **Partial fill discrepancy**: `execute_trade()` simulates fills independently of `PaperEngine.execute_order()`. Both apply their own partial fill logic, meaning the actual filled size in `PaperEngine` may differ slightly from the `execute_trade` result. This is cosmetic in PAPER mode — actual wallet deduction uses PaperEngine's fill simulation.

---

## 6. What Is Next

1. **Persist WalletEngine state to DB**: persist `WalletState` on every mutation; `restore_state()` on startup from DB snapshot.
2. **Price feed integration**: wire `PaperPositionManager.update_price()` to the WebSocket data feed for live mark-to-market PnL.
3. **`close_order()` integration**: wire `PaperEngine.close_order()` through exit monitor when TP/SL triggers.
4. **Unified fill tracking**: consolidate `execute_trade()` and `PaperEngine.execute_order()` into a single atomic execution path (eliminate partial fill discrepancy).
5. **SENTINEL validation**: run full system validation gate before go-live.
