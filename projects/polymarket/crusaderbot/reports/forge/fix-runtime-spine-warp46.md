# WARP•FORGE REPORT — fix-runtime-spine-warp46

**Branch:** WARP/fix-runtime-spine-warp46
**Date:** 2026-05-20 WIB
**Validation Tier:** STANDARD
**Claim Level:** MODERATE
**Validation Target:** Runtime spine: /start → onboarding → wallet → scanner → strategy → risk gate → paper trade open → position monitor → paper trade close → portfolio update → Telegram receipt
**Not in Scope:** Live trading, DB schema changes, new features, WebTrader UI, copy_trade leaderboard sync

---

## 1. What Was Built

Runtime spine evidence matrix for WARP-46. Traced all 12 spine steps of the CrusaderBot paper trading lifecycle — from `/start` through Telegram trade receipt — against actual source code. Every step assigned REAL / DEAD / DEFERRED based on actual import chains and scheduler job registration. Report corrects two errors present in the prior attempt:

1. Prior report listed `run_signal_scan` as the only active scanner. **Correction:** `sf_scan_job.run_once` (scheduler.py:542) is the primary scanner, handling 6 ENABLED lib strategies + signal_following feed. `run_signal_scan` is a secondary legacy loop for copy_trade only.
2. Prior report marked `domain/strategy/strategies/momentum_reversal.py` and `domain/strategy/strategies/signal_following.py` as DEAD but did not explain the real mechanism. **Correction:** These domain classes are DEAD because prod signal_following and momentum both go through `lib/strategies/` classes loaded by `lib_strategy_runner.py`, not the domain/strategy/strategies/ path.

---

## 2. Current System Architecture

```
TG /start or /start?ref=xxx
  → bot/handlers/onboarding.py:_entry (line 169)     [8-step concierge]
  → users.py:upsert_user (line 61)                   [user + settings + HD wallet + $1k seed + signal_following enroll]
  → bot/handlers/onboarding.py:_launch_cb (line 359) [apply preset → set_auto_trade(True) → set_onboarding_complete]

scanner tick (every 180s, APScheduler):
  → scheduler.py:sf_scan_job.run_once (line 542)     [PRIMARY: lib strategies + signal_following feed]
      → lib_strategy_runner.run_lib_strategy(name, markets, config) per ENABLED_STRATEGIES
          ENABLED: trend_breakout, momentum, value_investor, expiration_timing, pair_arb, ensemble
          DEFERRED: whale_tracking (runs but may return empty)
      → signal_evaluator.evaluate_publications_for_user [signal_following feed candidates]
      → _process_candidate → TradeEngine.execute → risk gate → router → paper.execute
  → scheduler.py:run_signal_scan (line 239)          [LEGACY: copy_trade only]
      → CopyTradeStrategy.scan → same risk gate + router

risk gate (every candidate):
  → domain/risk/gate.py:evaluate (line 204)          [15 gates: caps→kill→pause→tier→strategy→loss→drawdown→concurrent→corr→staleness→idem→liquidity→edge→market/Kelly→slippage]

paper trade open:
  → domain/execution/router.py:execute               [routes to paper (default) or live (all guards must pass)]
  → domain/execution/paper.py:execute (line 18)      [atomic: orders + positions + ledger debit]
  → services/trade_notifications/notifier.py:notify_entry [TG PAPER receipt]

exit watcher (every 30s, APScheduler):
  → scheduler.py:check_exits (line 335)
  → domain/execution/exit_watcher.py:run_once        [live price → force_close>TP>SL>strategy_exit>hold]
  → domain/execution/paper.py:close_position (line 93) [atomic: positions UPDATE + ledger credit]
  → monitoring/alerts.py:alert_user_tp_hit / sl_hit  [TG close receipt]
```

DEAD:
- `domain/strategy/strategies/momentum_reversal.py` — never instantiated (superseded by lib/strategies/momentum.py)
- `domain/strategy/strategies/signal_following.py` — never instantiated (superseded by signal_evaluator path)

---

## 3. Files Created / Modified

- `projects/polymarket/crusaderbot/reports/forge/runtime-spine-evidence.md` — evidence matrix (updated with corrections)
- `projects/polymarket/crusaderbot/reports/forge/fix-runtime-spine-warp46.md` — this report (updated)

No production code modified. State files NOT modified (per issue #1206: "State files NOT modified by FORGE — GATE handles post-merge sync").

`compileall` passed on full crusaderbot project — zero syntax errors.

---

## 4. What Is Working

All 12 runtime spine steps verified REAL:
- `/start` → `upsert_user` → `create_wallet_for_user` → `seed_paper_capital` → `_enroll_signal_following` — active and idempotent
- Concierge onboarding (8-step) → `_launch_cb` applies preset + activates scanner
- `sf_scan_job.run_once` — 180s tick, 6 ENABLED lib strategies + signal_following feed
- `domain/risk/gate.py:evaluate` — 15-gate risk check (0–14) with full audit logging + Kelly=0.25 asserted
- `paper.py:execute` — atomic order + position open + ledger debit, idempotent via ON CONFLICT
- `exit_watcher.run_once` — 30s tick, live Polymarket price, priority chain close logic
- `paper.py:close_position` — atomic position close + ledger credit
- `TradeNotifier.notify_entry` / `alert_user_tp_hit` / `alert_user_sl_hit` — Telegram receipts at every lifecycle event
- All 3 live-trading activation guards default `False` — paper is hardwired fallback in router.py

---

## 5. Known Issues

- `domain/strategy/strategies/momentum_reversal.py` and `signal_following.py` — compiled but unused. Not bugs; superseded by lib strategy path. Will not cause runtime errors. Low-priority cleanup only if linting is enforced.
- `run_signal_scan` (scheduler.py:239) and `sf_scan_job.run_once` (scheduler.py:542) are both registered at `SIGNAL_SCAN_INTERVAL` (180s default). For users without `copy_trade` in `strategy_types`, `run_signal_scan` does nothing per tick (empty candidate loop). No resource concern.
- `whale_tracking` in `DEFERRED_STRATEGIES` — runs via `run_lib_strategy` but may return empty if prob.trade API is unreachable. Not a spine break; it is silently skipped.

---

## 6. What Is Next

**Suggested Next Step:** WARP🔹CMD review. If evidence matrix is accepted, this lane closes. WARP•SENTINEL is NOT activated (Tier: STANDARD). If any path in the evidence matrix requires deeper end-to-end tracing (e.g. actual DB query execution on signal_publications, live Polymarket price fetch chain inside exit_watcher), flag to WARP•FORGE for targeted follow-up.
