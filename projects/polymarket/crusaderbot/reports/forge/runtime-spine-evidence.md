# CrusaderBot Runtime Spine — Evidence Matrix

**WARP-46 | Date:** 2026-05-20 | **Tier:** STANDARD | **Environment:** Paper-only

---

## Evidence Matrix

| Step | Code Path | File | Function | Line | Status | Evidence |
|------|-----------|------|----------|------|--------|----------|
| /start → onboarding | TG command dispatch | `bot/handlers/start.py` | `start_command` | 63 | **REAL** | Routes new users to welcome screen; calls `upsert_user()` line 66. 8-step concierge variant in `bot/handlers/onboarding.py:169` `_entry` also registered via `build_onboard_handler()`. |
| User state upsert | Create user + settings | `users.py` | `upsert_user` | 61 | **REAL** | Atomically inserts users + user_settings (ON CONFLICT DO NOTHING); calls `create_wallet_for_user()` line 99; calls `seed_paper_capital()` line 105; calls `_enroll_signal_following()` line 111. All idempotent. |
| Paper wallet init | HD wallet derive + ledger seed | `wallet/vault.py` | `create_wallet_for_user` | 26 | **REAL** | Derives HD address from WALLET_HD_SEED, stores encrypted key in wallets table. `users.py:seed_paper_capital` (line 119) credits $1,000 to ledger if balance=0. |
| Default strategy assignment | Preset apply + auto_trade activate | `bot/handlers/onboarding.py` | `_launch_cb` | 359 | **REAL** | Calls `get_preset(preset_key)` → `update_settings(user_id, active_preset=p.key, strategy_types=..., tp_pct, sl_pct, max_position_pct)` → `set_auto_trade(user_id, True)` → `set_paused(user_id, False)` → `set_onboarding_complete`. Also in `bot/handlers/start.py:skip_deposit_cb` line 204. |
| Active scanner tick (lib strategies) | APScheduler loop | `scheduler.py` | `sf_scan_job.run_once` | 542 | **REAL** | `sched.add_job(sf_scan_job.run_once, "interval", seconds=SIGNAL_SCAN_INTERVAL)` (default 180s). Fetches `auto_trade_on=TRUE AND paused=FALSE` users enrolled in `signal_following`. Runs all `ENABLED_STRATEGIES` + signal feed evaluator per user. |
| Active scanner tick (copy trade) | APScheduler loop | `scheduler.py` | `run_signal_scan` | 239 | **REAL** | Separate legacy loop also at 180s. Only activates if user has `copy_trade` in their `strategy_types`. Routes through the same risk gate + router. Both loops run on every tick — no conflict; they target different strategy_types. |
| Analysis engine — lib strategies | 6 active lib strategies | `services/signal_scan/lib_strategy_runner.py` | `run_lib_strategy` | 231 | **REAL** | `ENABLED_STRATEGIES = ("trend_breakout", "momentum", "value_investor", "expiration_timing", "pair_arb", "ensemble")`. Classes loaded from `lib/strategies/` via dynamic import. Each class called `.initialize(config)` then `.generate_signals(markets)`. Returns `SignalCandidate` list fed into `_process_candidate`. |
| Analysis engine — whale_tracking | Deferred lib strategy | `services/signal_scan/lib_strategy_runner.py` | `DEFERRED_STRATEGIES` | 44 | **DEFERRED** | `whale_tracking` class exists in `lib/strategies/whale_tracking.py` but is in `DEFERRED_STRATEGIES` — included in `strategies_to_run` list but requires external prob.trade API. Will execute but may return empty signals on API absence. Not a blocking issue. |
| Analysis engine — domain strategies | Legacy domain strategy classes | `domain/strategy/strategies/momentum_reversal.py` | `MomentumReversalStrategy` | — | **DEAD** | Compiled and importable but never instantiated in any scheduler job. `domain/strategy/strategies/signal_following.py:SignalFollowingStrategy` is also DEAD here — production signal_following goes through `services/signal_scan/signal_scan_job.py` → `signal_evaluator`, not this class. |
| Risk gate | 15-step evaluation | `domain/risk/gate.py` | `evaluate` | 204 | **REAL** | Called from `services/trade_engine/engine.py:141`. Gates 0–14: hard caps → kill switch → user pause → tier → strategy availability → daily loss → drawdown → concurrent → correlation → staleness → idempotency/dedup → liquidity → edge → market status + Kelly sizing → slippage. Every decision logged to risk_log. Kelly fraction hardcoded 0.25 (asserted line 348). |
| Paper trade open | Atomic order + position + debit | `domain/execution/paper.py` | `execute` | 18 | **REAL** | Single transaction: INSERT into orders (mode='paper', status='filled') + INSERT into positions (status='open') + ledger.debit_in_conn. Idempotent via ON CONFLICT(idempotency_key) DO NOTHING. Emits audit.write + TradeNotifier.notify_entry on success. |
| Position monitor (UI) | Telegram positions handler | `bot/handlers/positions.py` | `show_positions` | ~60 | **REAL** | Queries positions WHERE status='open', fetches CLOB midpoint for each token (3s timeout), renders per-position P&L card with Force Close button. Registered in dispatcher. |
| Position monitor (watcher) | Exit watcher tick | `scheduler.py` | `check_exits` | 335 | **REAL** | `sched.add_job(check_exits, "interval", seconds=EXIT_WATCH_INTERVAL)` (default 30s). Calls `exit_watcher.run_once()`. Fetches live Polymarket price per position → evaluate (force_close > TP > SL > strategy_exit > hold). |
| Paper trade close | TP/SL/force evaluation + close | `domain/execution/exit_watcher.py` | `_act_on_decision` | 236 | **REAL** | On `should_exit=True`: calls `order_module.submit_close_with_retry` → `router.close` → `paper_engine.close_position`. Atomic UPDATE positions (status='closed', pnl_usdc) + ledger.credit_in_conn (type='trade_close', proceeds). |
| Portfolio / PnL update | Ledger credit + balance update | `wallet/ledger.py` | `credit_in_conn` | 45 | **REAL** | Inserts ledger row + `UPDATE wallets SET balance_usdc = balance_usdc + $1`. Also `daily_pnl()` at line 83: SUM of trade_close + redeem + fee since day start — called by gate step 5 and position handlers. |
| Telegram receipt — entry | Trade open notification | `services/trade_notifications/notifier.py` | `TradeNotifier.notify_entry` | 159 | **REAL** | Called from `domain/execution/paper.py:77`. Formats entry card (market, side, size, price, TP/SL, strategy, mode=[PAPER]) with position ID button. Sends via `notifications.send`. |
| Telegram receipt — exit | TP/SL/force close notification | `monitoring/alerts.py` | `alert_user_tp_hit` / `alert_user_sl_hit` / `alert_user_force_close` | — | **REAL** | Called from `exit_watcher._act_on_decision` lines ~323–334. Sends close card with PnL. |

---

## Broken / Fake / Dead Path Map

| # | File | Line | What It Should Do | What It Does | Fix Required | Severity |
|---|------|------|-------------------|--------------|--------------|----------|
| 1 | `domain/strategy/strategies/momentum_reversal.py` | — | Active momentum scanner | Compiled + importable; never instantiated in any active scheduler job | No — superseded by `lib/strategies/momentum.py` via lib_strategy_runner | Low |
| 2 | `domain/strategy/strategies/signal_following.py` | — | Signal following strategy | Compiled + importable; never called — production signal_following uses `services/signal_scan/signal_scan_job.py` → `signal_evaluator` | No — superseded by signal_evaluator path | Low |
| 3 | `scheduler.py:run_signal_scan` (line 239) | 239 | Copy-trade signal scan | Runs at same 180s interval as `sf_scan_job.run_once`. Only fires if user has `copy_trade` in `strategy_types`; for all other users it iterates an empty candidate list — effectively a no-op per tick for non-copy-trade users | No — by design; two separate strategy pipelines | Informational |

No FAKE paths found. No hardcoded return values or mock data in any production execution path.

---

## Paper-Only Posture Proof

| Guard | File | Line | Default | Enforcement Location |
|-------|------|------|---------|---------------------|
| `ENABLE_LIVE_TRADING` | `config.py` | 148 | `False` | `domain/execution/live.py:60` (`assert_live_guards`) + `domain/risk/gate.py:136` (`_passes_live_guards`) |
| `EXECUTION_PATH_VALIDATED` | `config.py` | 149 | `False` | `domain/execution/live.py:62` |
| `CAPITAL_MODE_CONFIRMED` | `config.py` | 150 | `False` | `domain/execution/live.py:64` |
| `RISK_CONTROLS_VALIDATED` | `config.py` | 155 | `False` | Readiness validator; not yet wired to gate |

Live execution is unreachable unless ALL of `ENABLE_LIVE_TRADING`, `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED` are `True` via env override **AND** `USE_REAL_CLOB=True` **AND** user access_tier ≥ 4 **AND** user `trading_mode = 'live'`.

`domain/execution/router.py:100` routes to paper by default. If live path is requested but any guard is False, router logs `live_blocked_fallback_paper` audit event and falls to paper without crashing.

---

## Risk Gate Defaults

| Cap | Config Setting | Default | Line |
|-----|----------------|---------|------|
| Single position | `MAX_SINGLE_POSITION_PCT` | 10% | `config.py` ~159 |
| Total exposure | `MAX_TOTAL_EXPOSURE_PCT` | 80% | `config.py` ~160 |
| Daily loss floor | `MAX_DAILY_LOSS_USD` | -$50 | `config.py` ~161 |
| Max open positions | `MAX_OPEN_POSITIONS` | 20 | `config.py` ~162 |
| Kelly fraction (a) | hardcoded K.KELLY_FRACTION | 0.25 | `domain/risk/gate.py:348` (asserted) |
