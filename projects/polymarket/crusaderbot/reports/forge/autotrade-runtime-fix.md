# WARP•FORGE Report — autotrade-runtime-fix

**Branch:** WARP/CRUSADERBOT-AUTOTRADE-RUNTIME
**Date:** 2026-05-16
**Validation Tier:** MAJOR
**Claim Level:** FULL RUNTIME INTEGRATION
**Validation Target:** exit_watcher live-price feed · positions pnl_usdc · signal_scan open-position dedup · WebTrader badge display
**Not in Scope:** live CLOB execution path · redemption pipeline · DB schema migrations · risk gate constants · activation guards
**Suggested Next Step:** WARP•SENTINEL MAJOR audit before merge

---

## 1. What Was Built

Six runtime bugs diagnosed and fixed across the auto-trade pipeline and WebTrader dashboard.

**Root-cause chain:**
- BUG 1 (price not updating) caused BUG 3 (no new orders) via cascade: stale prices → TP/SL never fires → all 5 `max_concurrent` slots occupied → every new signal rejected at gate step 7.
- BUG 2 (duplicate positions) was an independent race condition in the signal scan.
- BUGs 4–6 were cosmetic WebTrader regressions from the dashboard PR.

**Fixes delivered:**

| Fix | Component | Change |
|-----|-----------|--------|
| FIX 1 | exit_watcher | Fetch live Gamma API price per position per tick; override stale DB price in TP/SL evaluation |
| FIX 1b | exit_watcher | Compute pnl_usdc from live price on every hold tick; persist via registry |
| FIX 1c | positions/registry | `update_current_price()` gains optional `pnl_usdc` param; atomic SET of both columns |
| FIX 1d | integrations/polymarket | `get_live_market_price()` — 30s TTL cache, one HTTP call per market per batch regardless of YES/NO position count |
| FIX 2 | signal_scan_job | `_has_open_position_for_market()` guard before engine execution; prevents duplicate open positions across concurrent ticks |
| FIX 4 | PositionTable.tsx | Fix `p.side === "BUY"` → `p.side === "yes"`; YES/NO badge rendering; OPEN/CLOSED uppercase |
| FIX 5 | WalletPage.tsx | `formatDate()` includes time ("May 13, 10:42"); `truncateHash()` suppresses "yes"/"no" notes |

---

## 2. Current System Architecture

```
APScheduler (check_exits every EXIT_WATCH_INTERVAL=30s)
  └── exit_watcher.run_once()
        └── registry.list_open_for_exit()           ← DB: positions JOIN markets JOIN users
        └── for each position:
              └── _fetch_live_price(market_id, side) ← GET gamma-api.polymarket.com/markets/{id}
                    └── get_live_market_price()       ← 30s TTL cache: lp:{market_id}
              └── evaluate(position, live_price=...)  ← TP/SL/force_close/strategy logic
              └── _act_on_decision()
                    ├── hold: _compute_pnl_usdc()
                    │          registry.update_current_price(..., pnl_usdc=...)
                    └── exit: order.submit_close_with_retry() → router.close → paper.close_position

APScheduler (sf_scan_job every SIGNAL_SCAN_INTERVAL)
  └── signal_scan_job.run_once()
        └── _load_enrolled_users()
        └── strategy.scan() → candidates
        └── _process_candidate()
              ├── crash-recovery: _load_stale_queued_row() [returns early if found]
              ├── pub dedup: _publication_already_queued()
              ├── [NEW] market dedup: _has_open_position_for_market()  ← FIX 2
              ├── _load_market()
              ├── _build_trade_signal()
              └── TradeEngine.execute() → risk gate (13 steps) → router_execute → paper fill
```

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/reports/forge/autotrade-runtime-fix.md` — this file

**Modified:**
- `projects/polymarket/crusaderbot/integrations/polymarket.py`
  — Added `get_live_market_price(market_id, side) -> Optional[float]`
  — Cache key `lp:{market_id}`, TTL 30s, reads `outcomePrices[0/1]`
  — Full error isolation: returns None on timeout, HTTP error, parse failure

- `projects/polymarket/crusaderbot/domain/execution/exit_watcher.py`
  — Import `get_live_market_price` from integrations
  — Added `_fetch_live_price(market_id, side)` error wrapper
  — Added `_compute_pnl_usdc(side, entry_price, current_price, size_usdc)` helper
  — `evaluate()`: new `live_price: Optional[float]` param; overrides `position.current_price()` when provided
  — `_act_on_decision()`: computes pnl_usdc in hold branch; passes to `registry.update_current_price()`
  — `run_once()`: fetches live price per position before evaluate call

- `projects/polymarket/crusaderbot/domain/positions/registry.py`
  — `update_current_price()`: new optional `pnl_usdc: Optional[float]` param
  — Two SQL branches: SET both columns when pnl_usdc provided, SET only current_price otherwise (backward-compat)

- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py`
  — Added `_has_open_position_for_market(user_id, market_id)` DB helper
  — Injected as step "1b" in `_process_candidate()` — after crash-recovery and pub dedup, before market load
  — Graceful degradation: falls through with warning on DB error; gate step 10 remains safety net

- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/PositionTable.tsx`
  — Side column: `p.side === "BUY"` → `p.side === "yes"`; renders "YES"/"NO" badge with green/red background
  — Status column: `{p.status}` → `{p.status.toUpperCase()}` with `font-medium` badge

- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/WalletPage.tsx`
  — `formatDate()`: uses `toLocaleString()` with `hour`/`minute` options
  — `truncateHash()`: suppresses "yes"/"no"/"true"/"false" notes (returns "")
  — Note `<p>` conditional: `entry.note && truncateHash(entry.note) &&` prevents empty tag render

---

## 4. What Is Working

- **Live price fetch:** `get_live_market_price()` queries Gamma API `outcomePrices` array; 30s TTL cache ensures one HTTP call per market per tick batch; full error isolation returns None on any failure.
- **TP/SL evaluation:** `evaluate()` now receives the live Gamma price via `live_price` param. `_return_pct()` computes per-side return against live mark. TP/SL comparison uses the same immutable `applied_tp_pct`/`applied_sl_pct` snapshots — behaviour of the priority chain is unchanged.
- **pnl_usdc persistence:** `_compute_pnl_usdc()` reuses `_return_pct()` formula for consistency. Persisted on every hold tick via `registry.update_current_price(..., pnl_usdc=pnl)`. Column exists in schema (migration 001) — no migration needed.
- **Price fallback:** If Gamma API is unreachable, `_fetch_live_price` returns None → `evaluate` uses `position.current_price()` → falls back to entry_price → ret_pct = 0 → no false TP/SL trigger. Safe degradation matches pre-fix behaviour.
- **Duplicate position guard:** `_has_open_position_for_market()` queries `positions` table (not `orders`) — the authoritative committed record. Crash-recovery resume path is above the new check and unaffected.
- **Frontend badges:** YES/NO with colour-coded pill badges; OPEN/CLOSED uppercase; date+time in wallet ("May 13, 10:42"); no raw "yes"/"no" ledger notes.

---

## 5. Known Issues

- `max_concurrent = 5` gate will remain blocked until the 5 existing stale positions close via TP/SL or force-close. New signals will flow once at least one position closes. No manual intervention required — FIX 1 enables the natural close path.
- Gamma API `outcomePrices` format (string vs float) is handled by `float(raw)` cast. If Polymarket changes the field name or nests prices differently, `_fetch_live_price` will return None and degrade safely.
- `pnl_usdc` on closed positions is written by the paper engine at close time (not the watcher); the watcher only writes it on hold ticks. Closed position PnL is unaffected by this change.
- No unit tests added in this lane — test coverage for `_fetch_live_price`, `_compute_pnl_usdc`, and `_has_open_position_for_market` deferred to WARP•SENTINEL scope.

---

## 6. What Is Next

```
WARP•SENTINEL validation required for autotrade-runtime-fix before merge.
Source: projects/polymarket/crusaderbot/reports/forge/autotrade-runtime-fix.md
Tier: MAJOR
```

Post-SENTINEL — if APPROVED:
- Monitor `job_runs` for `check_exits` — confirm `updated_count > 0` on first post-deploy tick
- Query `SELECT current_price, pnl_usdc FROM positions WHERE status='open'` — confirm values diverge from entry_price
- Query `SELECT * FROM risk_log WHERE gate_step=7 ORDER BY created_at DESC LIMIT 5` — step 7 rejections should clear once positions close
- Watch for new orders appearing in `orders` table within 5 min of first position close
