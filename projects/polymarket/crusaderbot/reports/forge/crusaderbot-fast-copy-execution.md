# WARP•FORGE Report — crusaderbot-fast-copy-execution

**Branch:** WARP/crusaderbot-fast-copy-execution
**Date:** 2026-05-11
**Validation Tier:** MAJOR
**Claim Level:** FULL RUNTIME INTEGRATION
**Validation Target:** Active paper copy-trade task execution path using Track A TradeEngine surface — wallet poll → task match → constraint filter → risk gate → paper position → idempotency + spend accounting
**Not in Scope:** Live trading activation, real CLOB, notifications UI, referral/fee system, copy trade exit tracking (leader-exit detection), leader bankroll auto-discovery
**Suggested Next Step:** WARP•SENTINEL validation of WARP/crusaderbot-fast-copy-execution before merge

---

## 1. What Was Built

Fast Track B: `CopyTradeMonitor` — a background service that monitors leader wallets and mirrors paper positions for all active `copy_trade_tasks`.

**`services/copy_trade/monitor.py`** — `CopyTradeMonitor` via `run_once()`

- `run_once()`: one monitor tick — kill switch guard, load active tasks, group by leader wallet, fetch recent leader trades, route each eligible trade through TradeEngine
- Per-task-per-trade pipeline:
  1. `_is_already_processed()` — check `copy_trade_idempotency` table (idempotency gate)
  2. `min_trade_size` filter — reject if leader trade below task threshold
  3. `_get_daily_spend()` — check `copy_trade_daily_spend` against `max_daily_spend` cap
  4. `_compute_copy_size()` — fixed mode uses `copy_amount` directly; proportional uses `scale_size` (with leader bankroll) or `mirror_size_direct` (fallback when bankroll unknown)
  5. `_resolve_side()` — normalises BUY/SELL → yes/no; applies `reverse_copy` flip
  6. Build `TradeSignal` with `strategy_type="copy_trade"`, `tp_pct`/`sl_pct` from task, idempotency key `copy_{task_id}_{leader_trade_id}`
  7. `TradeEngine.execute(signal)` — mandatory risk gate + paper fill
  8. On approval: `_record_spend()`, `_mark_processed()` — idempotency anchored
  9. On rejection: `_mark_processed()` — no re-evaluation on next tick
- Structured `structlog` logging: ACCEPTED, REJECTED (per constraint), DUPLICATE
- No live path, no guard mutations, asyncio only

**`domain/copy_trade/repository.py`** — added `list_active_tasks()`

- Fetches all `copy_trade_tasks` where `status = 'active'` across all users; used by the monitor tick

**`services/copy_trade/__init__.py`** — re-exports `run_once` from monitor

**`migrations/020_copy_trade_execution.sql`** — two new tables

- `copy_trade_idempotency (user_id, task_id, leader_trade_id)` — UNIQUE constraint, ON CONFLICT DO NOTHING safe
- `copy_trade_daily_spend (user_id, task_id, spend_date, spend_usdc)` — UNIQUE on (user_id, task_id, spend_date), upsert-safe with additive spend

**`scheduler.py`** — `CopyTradeMonitor` wired

- `copy_trade_monitor.run_once` registered as APScheduler job with id `copy_trade_monitor`, interval `COPY_TRADE_MONITOR_INTERVAL` (default 60s), `max_instances=1`, `coalesce=True`

**`config.py`** — `COPY_TRADE_MONITOR_INTERVAL: int = 60` added

**`tests/test_fast_track_b.py`** — 23 hermetic tests

- 13 async integration tests covering: accepted end-to-end, min_trade_size rejection, daily spend cap, idempotency duplicate, risk gate rejection, idempotency row correct args, spend recorded, unknown side rejection, reverse_copy flip, spend-cap floor rejection, kill switch exit, no tasks noop, wallet API propagation guard
- 10 pure helper tests: `_extract_trade_id` (3 cases), `_resolve_side` (4 cases), `_make_idempotency_key`, `_compute_copy_size` (2 modes)

```
23 passed in 0.50s
```

---

## 2. Current System Architecture

```
APScheduler (scheduler.py)
        │
        └─► services/copy_trade/monitor.py          ← NEW: CopyTradeMonitor
                run_once() — every COPY_TRADE_MONITOR_INTERVAL (60s default)
                  │
                  ├─► kill_switch_is_active()         ← immediate exit if active
                  │
                  ├─► domain/copy_trade/repository.list_active_tasks()
                  │       → list[CopyTradeTask]        ← all status='active' tasks
                  │
                  └─► for each leader wallet:
                        fetch_recent_wallet_trades()   ← existing wallet_watcher
                          rate-limited 1 req/s, 5s timeout
                        │
                        for each task × trade:
                          _is_already_processed()      ← copy_trade_idempotency
                          min_trade_size filter
                          _get_daily_spend()           ← copy_trade_daily_spend
                          _compute_copy_size()         ← scaler (fixed / proportional)
                          _resolve_side() + reverse_copy
                          _load_user_context()
                          │
                          ▼ TradeSignal (strategy_type="copy_trade")
                          │
                          services/trade_engine/engine.py
                            TradeEngine.execute(signal)
                              │
                              ├─► domain/risk/gate.py      ← 13-step risk gate (mandatory)
                              │
                              └─► domain/execution/router.py → paper.execute()
                                      INSERT orders + positions (paper mode)
                                      ledger.debit_in_conn()
                          │
                          On approval:
                            _record_spend()            ← copy_trade_daily_spend upsert
                            _mark_processed()          ← copy_trade_idempotency INSERT

Idempotency key: "copy_{task_id}_{leader_trade_id}"
DB tables (new):
  copy_trade_idempotency   — (user_id, task_id, leader_trade_id) UNIQUE
  copy_trade_daily_spend   — (user_id, task_id, spend_date, spend_usdc) UNIQUE
```

Activation guards unchanged:
- `ENABLE_LIVE_TRADING` — NOT SET
- `EXECUTION_PATH_VALIDATED` — NOT SET
- `CAPITAL_MODE_CONFIRMED` — NOT SET
- `USE_REAL_CLOB` — NOT SET (default False)

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/services/copy_trade/monitor.py`
- `projects/polymarket/crusaderbot/migrations/020_copy_trade_execution.sql`
- `projects/polymarket/crusaderbot/tests/test_fast_track_b.py`

**Modified:**
- `projects/polymarket/crusaderbot/domain/copy_trade/repository.py` — added `list_active_tasks()`
- `projects/polymarket/crusaderbot/services/copy_trade/__init__.py` — re-exports `run_once`
- `projects/polymarket/crusaderbot/scheduler.py` — wired `copy_trade_monitor.run_once`
- `projects/polymarket/crusaderbot/config.py` — added `COPY_TRADE_MONITOR_INTERVAL`
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-fast-copy-execution.md` (this file)

No activation guards touched. No live execution paths added. No existing files rewritten.

---

## 4. What Is Working

- `CopyTradeMonitor.run_once()` correctly groups tasks by leader wallet to minimise Polymarket API calls (one fetch per unique wallet per tick, not one per task)
- Kill switch guard exits immediately without touching any execution path
- `min_trade_size` constraint: leader trades below the per-task threshold are silently skipped (structlog REJECTED)
- Daily `max_daily_spend` cap: correctly reads `copy_trade_daily_spend` and blocks execution when cap reached; remaining budget caps copy size
- Idempotency: `copy_trade_idempotency` row persisted on both approval AND risk-gate rejection — prevents re-evaluation on next tick for permanently-rejected trades
- `reverse_copy` correctly flips YES/NO side before building `TradeSignal`
- Fixed copy mode: uses `copy_amount` directly
- Proportional copy mode: uses `scale_size` when leader bankroll available in trade dict; falls back to `mirror_size_direct` otherwise
- All signals route through `TradeEngine.execute()` — risk gate is mandatory before any paper position is created
- `strategy_type="copy_trade"` on orders and positions; idempotency key encodes `(task_id, leader_trade_id)` for traceability
- Structured structlog logging: ACCEPTED/REJECTED/DUPLICATE with full context (copy_task_id, leader_wallet, leader_trade_id, size, mode, position_id)
- Scheduler registration: `copy_trade_monitor` job with `max_instances=1` / `coalesce=True` prevents overlapping ticks
- 23/23 hermetic tests pass (0.50s)

---

## 5. Known Issues

- Leader wallet `bankroll` / `portfolioValue` field is rarely present in Polymarket Data API activity responses; proportional mode degrades to `mirror_size_direct` in almost all real cases. A dedicated leader-profile lookup (Gamma API `GET /profiles/{addr}`) would fix this — deferred to Track D or a follow-up lane.
- `_extract_price()` falls back to `0.5` when no price field is present in the leader trade. The risk gate's `market_status` check and paper engine's price storage will accept this, but the position entry price will be inaccurate. Real Polymarket activity records always carry a `price` field; this fallback is defensive only.
- `_extract_liquidity()` falls back to `50_000.0` USDC when absent. This is intentionally generous to prevent the risk gate's market-liquidity check from spuriously rejecting copy trades. In the paper posture this is safe; for live activation a real liquidity lookup would be required.
- Market context (question, yes/no token IDs) is extracted from the leader trade dict. The Polymarket Data API activity endpoint carries `conditionId` but not always `question` or token IDs. The paper engine accepts `None` for `market_question`; token IDs are not used in paper mode. For live mode these would need to be fetched from the `markets` DB table.
- `copy_trade_daily_spend` uses UTC date. If the user's local day (Asia/Jakarta, UTC+7) wraps at a different time than UTC midnight, the spend cap resets ~7 hours earlier than the user's subjective "today". This is a P3 cosmetic issue — no safety implication.

---

## 6. What Is Next

1. WARP•SENTINEL validation of WARP/crusaderbot-fast-copy-execution (Tier MAJOR — mandatory before merge)
2. After Track B merge: Track C (trade notifications) can add copy-trade entry and exit events targeting `TradeResult` surface
3. After Track B merge: Track D (risk caps + kill switch hardening) builds on the active execution path
4. Follow-up: leader-profile Gamma API lookup for accurate bankroll in proportional mode
5. Follow-up: market context hydration from `markets` DB table when leader trade lacks `question` / token IDs
