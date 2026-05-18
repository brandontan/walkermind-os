# WARP•FORGE Report — fast-trade-engine

**Branch:** WARP/CRUSADERBOT-FAST-TRADE-ENGINE
**Date:** 2026-05-17 22:00 Asia/Jakarta
**Validation Tier:** MAJOR
**Claim Level:** FULL RUNTIME INTEGRATION
**Validation Target:** Signal-to-order pipeline + TP/SL auto-close worker, paper mode only
**Not in Scope:** Live execution path, copy-trade (Track B), Telegram handler changes

---

## 1. What Was Built

Track A: Signal-to-Order + TP/SL pipeline audit and hardening.

**Architecture audit confirmed** all Track A components fully implemented and wired. One gap
identified and closed: `EXIT_WATCH_INTERVAL` default was 60s; spec requires 30s. Fixed in
`config.py`. Scheduler wiring tests added to `test_fast_track_a.py` to permanently enforce
the 30s contract.

**Signal-to-Order pipeline** (fully in place, verified):
- `services/trade_engine/engine.py` — `TradeEngine.execute()` routes signal → 13-step risk
  gate → paper execute → atomic wallet debit. Gate is always evaluated first; router is never
  called on rejection.
- `services/signal_scan/signal_scan_job.py` — per-user, per-tick scan loop that builds
  `TradeSignal`, calls `TradeEngine`, writes to `execution_queue`, and handles crash recovery.
- `domain/execution/paper.py` — `execute()` atomic INSERT (orders + positions + ledger debit)
  in a single transaction. `ON CONFLICT ... DO NOTHING` on idempotency_key is the dedup floor.

**TP/SL background worker** (fully in place, verified):
- `domain/execution/exit_watcher.py` — `run_once()` covers: force_close_intent (priority 1),
  TP_HIT, SL_HIT, strategy_exit, MARKET_EXPIRED (Phase A/B two-phase sweep). Per-position
  exception isolation prevents a single bad row from killing the full batch.
- `scheduler.py` — `check_exits()` wired as APScheduler job id `exit_watch`, interval now 30s
  (was 60s), `max_instances=1`, `coalesce=True`.
- `domain/execution/paper.py` — `close_position()` atomic UPDATE + wallet credit in one
  transaction. Already-closed guard (WHERE status='open') prevents double credit.

---

## 2. Current System Architecture

```
Signal Scanner (market_signal_scanner.py — 60s)
    ↓  writes signal_publications rows
Signal Following Strategy (signal_following.py)
    ↓  produces SignalCandidate per active publication
Signal Scan Job (signal_scan_job.py — 180s)
    ↓  builds TradeSignal per candidate per enrolled user
TradeEngine.execute() (services/trade_engine/engine.py)
    ↓  13-step risk gate (domain/risk/gate.py)
    ↓  on approval: router.execute → paper.execute (atomic)
    ↓       INSERT orders, INSERT positions, debit wallet (single tx)
    ↓  returns TradeResult (approved/rejected/duplicate)
signal_scan_job writes execution_queue row, marks executed
    ↓
[positions table — status='open']
    ↓
Exit Watcher run_once() — APScheduler every 30s (scheduler.check_exits)
    ↓  per position: fetch live price (Gamma API)
    ↓  evaluate: force_close_intent > TP_HIT > SL_HIT > STRATEGY_EXIT > hold
    ↓  on exit: paper.close_position (atomic: UPDATE positions + credit wallet)
    ↓  on hold: update current_price + pnl_usdc
[audit trail every open/close via audit.write()]
[user Telegram alert via TradeNotifier]
```

---

## 3. Files Created / Modified

**Modified:**
- `projects/polymarket/crusaderbot/config.py:180` — `EXIT_WATCH_INTERVAL` default 60 → 30
- `projects/polymarket/crusaderbot/tests/test_fast_track_a.py` — added `TestSchedulerWiring`
  class (2 tests): `test_exit_watch_job_registered_at_30s` and `test_exit_watch_max_instances_one`

**No migration needed:** All required positions table columns already present via migration 005:
`applied_tp_pct`, `applied_sl_pct`, `force_close_intent`, `close_failure_count`, plus DB trigger
that snapshot-copies tp_pct→applied_tp_pct on INSERT and enforces immutability on UPDATE.

---

## 4. What Is Working

- Signal → risk gate → paper position open → wallet debit: atomic, idempotent, user-scoped.
- TP/SL auto-close at 30s cadence: per-position exception isolation, no cross-position bleed.
- Paper close: atomic UPDATE positions + credit wallet; already-closed guard prevents double credit.
- MARKET_EXPIRED: two-phase (stale Gamma price + resolved DB flag); capital returned on close.
- Force close (emergency): priority 1, beats TP/SL. Set by Telegram emergency flow.
- Dedup: dual-layer (idempotency_key + execution_queue UNIQUE constraint).
- Kill switch: `kill_switch_is_active()` checked before crash-recovery resume.
- Paper-only posture enforced: `ENABLE_LIVE_TRADING=false` by default; all 4 activation guards
  off; risk gate returns chosen_mode="paper" with guards off.
- Test suite: 49 hermetic tests pass (0 fail). Covers gate rejections, approved paths, TP/SL
  priority chain, edge cases (no tp/sl, resolved market, force close, duplicate), scan path
  integration, scheduler wiring.

---

## 5. Known Issues

- None introduced by this lane.
- Pre-existing deferred items preserved from PROJECT_STATE.md — not in scope here.

---

## 6. What Is Next

- WARP•SENTINEL validation required before merge (Validation Tier: MAJOR).
- Track B (copy trade) depends on this merge — do not proceed to Track B until SENTINEL clears Track A.
- Source: `projects/polymarket/crusaderbot/reports/forge/fast-trade-engine.md`

---

**Suggested Next Step:**
WARP•SENTINEL validation of Track A before merge.
Source: `projects/polymarket/crusaderbot/reports/forge/fast-trade-engine.md`
Tier: MAJOR
