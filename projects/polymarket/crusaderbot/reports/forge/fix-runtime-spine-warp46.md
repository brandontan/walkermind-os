# WARP•FORGE REPORT — fix-runtime-spine-warp46

**Branch:** WARP/fix-runtime-spine-warp46
**Date:** 2026-05-20 WIB
**Validation Tier:** STANDARD
**Claim Level:** MODERATE
**Validation Target:** Runtime spine: /start → onboarding → wallet → scanner → strategy → risk gate → paper trade open → position monitor → paper trade close → portfolio update → Telegram receipt
**Not in Scope:** Live trading, DB schema changes, new features, WebTrader UI

---

## 1. What Was Built

Runtime spine evidence matrix for WARP-46. Traced all 12 steps of the CrusaderBot paper trading lifecycle — from `/start` through Telegram trade receipt — against actual source code. Produced `runtime-spine-evidence.md` with exact file paths, function names, line numbers, and REAL/FAKE/DEAD classification for every step. Dead path map and paper-only posture proof included.

---

## 2. Current System Architecture

Pipeline (all REAL in paper mode):

```
TG /start
  → bot/handlers/start.py:start_command (line 63)
  → users.py:upsert_user (line 61)         [user + settings + wallet + $1k seed + signal_following enroll]
  → scheduler.py:run_signal_scan (line 239) [180s tick, auto_trade_on users]
  → domain/signal/copy_trade.py:CopyTradeStrategy.scan [only active strategy]
  → domain/risk/gate.py:evaluate (line 204) [15 cumulative gates, codes 0–14]
  → domain/execution/router.py:execute      [routes to paper (default) or live (guarded)]
  → domain/execution/paper.py:execute (line 18) [atomic: order + position + ledger debit]
  → services/trade_notifications/notifier.py:notify_entry [TG entry receipt]
  → scheduler.py:check_exits (line 335)     [30s tick]
  → domain/execution/exit_watcher.py:run_once (line 418) [live price → TP/SL eval → close]
  → domain/execution/paper.py:close_position (line 93) [atomic: position close + ledger credit]
  → monitoring/alerts.py:alert_user_tp_hit/sl_hit [TG exit receipt]
  → jobs/daily_pnl_summary.py:run_job (line 317) [23:00 cron, daily PnL TG send]
```

DEAD strategies (compiled, never instantiated):
- `domain/strategy/strategies/momentum_reversal.py:MomentumReversalStrategy`
- `domain/strategy/strategies/signal_following.py:SignalFollowingStrategy`

---

## 3. Files Created / Modified

- `projects/polymarket/crusaderbot/reports/forge/runtime-spine-evidence.md` — evidence matrix (created)
- `projects/polymarket/crusaderbot/reports/forge/fix-runtime-spine-warp46.md` — this report (created)

No production code modified. State files NOT modified (per issue #1206 instructions).

---

## 4. What Is Working

All 12 runtime spine steps verified REAL:
- `/start` handler, `upsert_user`, `seed_paper_capital`, `_enroll_signal_following` — active and idempotent
- `run_signal_scan` → `CopyTradeStrategy.scan` — live loop every 180s
- `gate.py:evaluate` — 15-gate risk check (codes 0–14) with full audit logging to risk_log table
- `paper.py:execute` — atomic order + position open + ledger debit
- `exit_watcher.run_once` — 30s tick, live Polymarket price fetch, TP/SL evaluation
- `paper.py:close_position` — atomic position close + ledger credit
- `notify_entry` / `alert_user_tp_hit` / `daily_pnl_summary` — Telegram receipts at every lifecycle event
- All 4 live-trading guards default to `False` — paper is hardwired fallback

---

## 5. Known Issues

- `MomentumReversalStrategy` and `SignalFollowingStrategy` are compiled and imported but never instantiated in `scheduler._strategies`. Not a runtime bug — these strategies are not in scope for current paper sprint. They will produce unused import warnings if linting is strict. No fix required unless WARP🔹CMD activates these strategies.
- Signal scan interval defaults to 180s (`SIGNAL_SCAN_INTERVAL`); copy trade monitor runs at 60s (`COPY_TRADE_MONITOR_INTERVAL`). These are independent loops.

---

## 6. What Is Next

**Suggested Next Step:** WARP🔹CMD review of this evidence matrix. If any step is marked incorrectly or a path needs deeper tracing (e.g. copy_trade_tasks vs copy_targets table, Polymarket API call chain inside CopyTradeStrategy), flag to WARP•FORGE for targeted follow-up. WARP-47 WebTrader realtime trust fix is the parallel active lane.
