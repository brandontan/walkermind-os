# CrusaderBot Runtime Spine — Evidence Matrix

**WARP-46 | Date:** 2026-05-20 | **Tier:** STANDARD | **Environment:** Paper-only

---

## Evidence Matrix

| Step | Code Path | File | Function | Line | Status | Evidence |
|------|-----------|------|----------|------|--------|----------|
| /start → onboarding | TG command dispatch | `bot/handlers/start.py` | `start_command` | 63 | **REAL** | Routes new users to welcome screen; calls `upsert_user()` line 66–67 |
| User state upsert | Create user + settings + wallet init | `users.py` | `upsert_user` | 61 | **REAL** | Atomically inserts users + user_settings (ON CONFLICT DO NOTHING); calls `seed_paper_capital()` line 105; calls `_enroll_signal_following()` line 111 |
| Paper wallet init | Seed $1,000 USDC | `users.py` | `seed_paper_capital` | 119 | **REAL** | Inserts wallets row + ledger debit entry; idempotent via ledger note check |
| Default strategy assignment | Enroll signal_following demo feed | `users.py` | `_enroll_signal_following` | 15 | **REAL** | Creates demo feed UUID `00000000-0000-0000-0001-000000000001`; inserts user_signal_subscriptions on every /start (idempotent) |
| Active scanner tick | APScheduler loop | `scheduler.py` | `run_signal_scan` | 239 | **REAL** | Runs every `SIGNAL_SCAN_INTERVAL` (default 180s); fetches `auto_trade_on=TRUE` + `paused=FALSE` users; iterates `_strategies` dict |
| Analysis engine | Strategy scan | `domain/signal/copy_trade.py` | `CopyTradeStrategy.scan` | 18 | **REAL** | Only active strategy in `scheduler._strategies` (line 236); queries copy_targets; returns `SignalCandidate` list |
| Analysis engine | Momentum Reversal | `domain/strategy/strategies/momentum_reversal.py` | `MomentumReversalStrategy` | — | **DEAD** | Imported in `__init__.py` line 9; never instantiated in `scheduler._strategies`; `.scan()` never called in production |
| Analysis engine | Signal Following | `domain/strategy/strategies/signal_following.py` | `SignalFollowingStrategy` | — | **DEAD** | Imported in `__init__.py` line 10; never instantiated in `scheduler._strategies`; `.scan()` never called in production |
| Risk gate | 15-gate evaluation | `domain/risk/gate.py` | `evaluate` | 204 | **REAL** | Called from `scheduler._process_candidate()` line 304; gates (0–14): hard caps → kill switch → user pause → tier → strategy availability → daily loss → drawdown → concurrent → correlation → staleness → idempotency → liquidity → edge → market status/Kelly → slippage; logs every decision to risk_log |
| Paper trade open | Atomic order + position + debit | `domain/execution/paper.py` | `execute` | 18 | **REAL** | Inserts orders (mode='paper', status='filled') + positions (status='open') + ledger debit in single transaction; emits audit + Telegram entry notification |
| Position monitor | Exit watcher tick | `scheduler.py` | `check_exits` | 335 | **REAL** | APScheduler job every `EXIT_WATCH_INTERVAL` (default 30s); calls `exit_watcher.run_once()` |
| Paper trade close | TP/SL/force evaluation + close | `domain/execution/exit_watcher.py` | `run_once` | 418 | **REAL** | Fetches live Polymarket price → `evaluate()` → `_act_on_decision()` → `router.close()` → `paper.close_position()` |
| Portfolio / PnL update | Ledger credit on close | `wallet/ledger.py` | `credit_in_conn` | 45 | **REAL** | Inserts ledger row (type='trade_close') + increments wallets.balance_usdc; atomic within transaction |
| Telegram receipt | Entry notification | `services/trade_notifications/notifier.py` | `TradeNotifier.notify_entry` | — | **REAL** | Called from `paper.execute()` line 77; formats entry message (market, side, size, price, TP/SL, mode, strategy) |
| Telegram receipt | Exit notification | `monitoring/alerts.py` | `alert_user_tp_hit` / `alert_user_sl_hit` | — | **REAL** | Called from `exit_watcher._act_on_decision()` lines 327–337; sends close + PnL receipt |
| Telegram receipt | Daily PnL summary | `jobs/daily_pnl_summary.py` | `run_job` | 317 | **REAL** | APScheduler cron 23:00 Jakarta; queries positions.pnl_usdc (closed today) + ledger fees + unrealized; sends to opted-in users |

---

## Broken / Fake / Dead Path Map

| # | File | Line | What It Should Do | What It Does | Fix Required | Severity |
|---|------|------|-------------------|--------------|--------------|----------|
| 1 | `domain/strategy/strategies/momentum_reversal.py` | — | Active momentum scanner producing signals | Compiled but never instantiated in `scheduler._strategies` | No — strategy not in active scope | Low (by design) |
| 2 | `domain/strategy/strategies/signal_following.py` | — | Signal following scanner loop | Same as above — compiled but never called | No — strategy not in active scope | Low (by design) |

No FAKE paths found (no hardcoded/mock data in production execution paths).

---

## Paper-Only Posture Proof

| Guard | File | Line | Default | Verified |
|-------|------|------|---------|----------|
| `ENABLE_LIVE_TRADING` | `config.py` | 148 | `False` | ✓ |
| `EXECUTION_PATH_VALIDATED` | `config.py` | 149 | `False` | ✓ |
| `CAPITAL_MODE_CONFIRMED` | `config.py` | 150 | `False` | ✓ |
| `RISK_CONTROLS_VALIDATED` | `config.py` | 155 | `False` | ✓ |

Live execution is unreachable unless ALL four guards are set to `True` via environment override **AND** user access_tier ≥ 4 **AND** user `trading_mode = 'live'`. Paper is the hardwired fallback in `domain/execution/router.py` line 100.

---

## Risk Gate Defaults

| Cap | Config Setting | Default | Line |
|-----|----------------|---------|------|
| Single position | `MAX_SINGLE_POSITION_PCT` | 10% | 159 |
| Total exposure | `MAX_TOTAL_EXPOSURE_PCT` | 80% | 160 |
| Daily loss floor | `MAX_DAILY_LOSS_USD` | -$50 | 161 |
| Max open positions | `MAX_OPEN_POSITIONS` | 20 | 162 |
| Kelly fraction (a) | Hardcoded | 0.25 | — |
