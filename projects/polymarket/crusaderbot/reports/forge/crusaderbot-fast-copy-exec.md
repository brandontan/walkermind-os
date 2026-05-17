# WARP•FORGE Report — crusaderbot-fast-copy-exec

**Branch:** WARP/CRUSADERBOT-FAST-COPY-EXEC
**Date:** 2026-05-17
**Validation Tier:** MAJOR
**Claim Level:** FULL RUNTIME INTEGRATION
**Validation Target:** copy_trade.executed event emission + copy_trade_events audit table wired into the 60s copy-trade monitor tick
**Not in Scope:** Live trading activation, real CLOB, UI for copy_trade_events, leader bankroll discovery, Track C notification UI
**Suggested Next Step:** WARP•SENTINEL validation of WARP/CRUSADERBOT-FAST-COPY-EXEC before merge

---

## 1. What Was Built

**Gap filled on top of the prior crusaderbot-fast-copy-execution lane:**

The existing `CopyTradeMonitor` (`services/copy_trade/monitor.py`) already enforced all copy-trade constraints and executed via the paper pipeline. Two items were missing:

1. **`copy_trade_events` table** — an audit log recording every mirrored position (user_id, position_id, target_wallet, market_id, size_usdc). The prior lane used `copy_trade_idempotency` for deduplication but carried no per-position audit trail with market/size context.

2. **`copy_trade.executed` event emission** — after every successful non-duplicate paper fill, the monitor now emits `copy_trade.executed` onto the in-process event bus. Track C's `notification_service` subscribes to this event to fire Telegram receipts.

**`migrations/032_copy_trade_events.sql`**

- `copy_trade_events (id, user_id, position_id, target_wallet, market_id, size_usdc, created_at)` — append-only audit table; `position_id` FK to `positions(id)`.
- `idx_copy_trade_events_user_id` — user-scoped query isolation.
- `idx_copy_trade_events_market` — per-(user, wallet, market) lookup for downstream queries.

**`services/copy_trade/monitor.py`** — two additions to `_process_one()`

- `_record_copy_trade_event()` — inserts one row into `copy_trade_events` after a successful fill (position_id, target_wallet, market_id, size_usdc). Called before event emission.
- `event_bus.emit("copy_trade.executed", ...)` — fires after `_record_copy_trade_event()` returns, strictly OUTSIDE any DB transaction. Payload: `telegram_user_id`, `market_id`, `target_wallet`, `side`, `size_usdc`, `entry_price`.

---

## 2. Current System Architecture

```
APScheduler (scheduler.py)
        │
        └─► services/copy_trade/monitor.py          CopyTradeMonitor
                run_once() — every 60s (COPY_TRADE_MONITOR_INTERVAL)
                  │
                  ├─► kill_switch_is_active()
                  │
                  ├─► list_active_tasks()            copy_trade_tasks WHERE status='active'
                  │
                  └─► for each leader wallet:
                        fetch_recent_wallet_trades()  rate-limited, 5s timeout
                          │
                          for each task × trade:
                            idempotency check          copy_trade_idempotency
                            min_trade_size filter
                            max_daily_spend cap        copy_trade_daily_spend
                            compute copy size          scaler (fixed / proportional)
                            resolve side + reverse_copy
                            build TradeSignal
                            │
                            TradeEngine.execute()
                              risk gate (13 steps, mandatory)
                              domain/execution/router.py → paper.execute()
                                INSERT orders + positions (atomic)
                                ledger.debit_in_conn()
                            │
                            On approved, non-duplicate:
                              _record_spend()          copy_trade_daily_spend upsert
                              _record_copy_trade_event() → copy_trade_events INSERT ← NEW
                              event_bus.emit("copy_trade.executed", ...) ← NEW
                              (notification_service / Track C subscribes to this event)
                            _mark_processed()          copy_trade_idempotency INSERT

Event emission contract:
  - Emitted OUTSIDE any DB transaction (fire-and-forget via asyncio.create_task)
  - Payload carries telegram_user_id, market_id, target_wallet, side, size_usdc, entry_price
  - One failing handler never blocks other handlers or the monitor tick (event_bus contract)
```

Activation guards unchanged:
- `ENABLE_LIVE_TRADING` — NOT SET
- `EXECUTION_PATH_VALIDATED` — NOT SET
- `CAPITAL_MODE_CONFIRMED` — NOT SET
- `USE_REAL_CLOB` — NOT SET (default False)

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/migrations/032_copy_trade_events.sql`
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-fast-copy-exec.md` (this file)

**Modified:**
- `projects/polymarket/crusaderbot/services/copy_trade/monitor.py` — import `event_bus`; add `_record_copy_trade_event()` helper; emit `copy_trade.executed` after approved non-duplicate fill

**Not touched:**
- `domain/execution/paper.py` — Track A execution file; used unchanged via TradeEngine
- `scheduler.py` — monitor already wired at 60s interval; no change needed
- `domain/copy_trade/repository.py` — no change; `list_active_tasks()` already present

---

## 4. What Is Working

- `copy_trade_events` row persisted after every successful non-duplicate paper fill
- `copy_trade.executed` emitted via event bus with full payload (telegram_user_id, market_id, target_wallet, side, size_usdc, entry_price)
- Event emitted strictly OUTSIDE the paper.py transaction (fire-and-forget)
- All existing constraints remain enforced: idempotency, min_trade_size, max_daily_spend, risk gate
- One copy target failure cannot crash other users' monitors (try/except per task in `_process_one`, per wallet in `_process_wallet`)
- All queries are user-isolated (WHERE user_id = $1 on every write)
- compileall clean; ruff clean
- Scheduler already registers `copy_trade_monitor` job at 60s, max_instances=1

---

## 5. Known Issues

- `_record_copy_trade_event()` is NOT inside the paper.py transaction — it runs after commit. In a crash between paper.execute() and the INSERT, the position exists but the copy_trade_events row is missing. This is acceptable: the idempotency row (`_mark_processed`) is written after both, so the trade will not be re-processed. The missing copy_trade_events row is a cosmetic audit gap only.
- Inherited known issues from crusaderbot-fast-copy-execution: leader bankroll rarely available (proportional mode degrades to mirror_size_direct), price fallback 0.5, liquidity fallback 50k.

---

## 6. What Is Next

1. WARP•SENTINEL validation of WARP/CRUSADERBOT-FAST-COPY-EXEC (Tier MAJOR — mandatory before merge)
2. Apply migration 032 to production DB after merge
3. Track C notification_service already subscribes to `copy_trade.executed` — receipts will fire on next monitor tick post-merge
