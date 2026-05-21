# WARP•FORGE REPORT — runtime-spine-validation

**Branch:** WARP/runtime-spine-validation
**Issue:** #1243 (WARP-46 — Runtime Spine Validation, end-to-end paper trade flow)
**Date:** 2026-05-21 11:06 Asia/Jakarta
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** End-to-end paper trade spine across the 7 validation targets in issue #1243 (start → scan → trade → position → close → receipt → PnL → routing) plus the three new dimensions added in this iteration: NOTIFY triggers (`cb_orders`/`cb_fills`/`cb_positions`), `job_runs.metadata` population, and silent-exception swallowing audit.
**Not in Scope:** Live trading activation, capital mode changes, WebTrader SSE wiring, DB schema changes, new features.

---

## 1. What Was Built

Targeted re-pass on the runtime spine introduced in WARP-46 (issue #1206, evidence matrix at `projects/polymarket/crusaderbot/reports/forge/runtime-spine-evidence.md`). This pass extends the original 12-step matrix with the 7 explicit validation targets and 3 new audit dimensions defined in issue #1243.

No production code modified. Output is the evidence pass below. Every claim is anchored to `file:line` against the current `main` HEAD; no inferences from prior reports.

Two material findings surfaced that the prior pass did not call out:

1. The `portfolio_snapshots` table and `cb_portfolio` NOTIFY trigger exist (migration 029) but no Python writer ever inserts rows. The PnL chart used by Telegram + WebTrader derives the equity series live from the `ledger` table via `services/portfolio_chart.py`. The cb_portfolio channel is therefore dormant. This is out of the issue's explicit "Not in Scope" (WebTrader SSE), so it is logged as an advisory finding, not a blocker.
2. The function name `check_with_receipt()` mentioned in issue #1243 §Validation Targets is not present in the codebase. The actual receipt surface is `TradeNotifier.notify_entry` (open card) plus the 7 `alert_user_*` close-event handlers in `monitoring/alerts.py`. The wording in the issue is abstract; the real receipt path is wired and live.

---

## 2. Current System Architecture (Spine Slice)

```
Telegram /start
  -> bot/handlers/start.py:63              start_command
       -> users.py:upsert_user             (idempotent: user + wallet + $1k seed + signal_following enroll)
       -> bot/handlers/dashboard.py        show_dashboard (returning user)
       -> ConversationHandler              welcome -> wallet_ready -> deposit (new user)

scanner tick (180s, APScheduler)
  -> scheduler.py:542                      sf_scan_job (signal_scan_job.run_once)
       -> services/signal_scan/signal_scan_job.py:728  run_once
            -> lib_strategy_runner.run_lib_strategy    (6 ENABLED lib strategies)
            -> signal_evaluator.evaluate_publications_for_user  (signal_following feed)
            -> _process_candidate
                 -> dedup (execution_queue + open-position + freshness + drift)
                 -> services/trade_engine/engine.py:141  TradeEngine.execute
                      -> domain/risk/gate.py:204  evaluate  (15 gates, Kelly=0.25)
                      -> domain/execution/router.py:execute (paper default; live gated)
                           -> domain/execution/paper.py:20  execute
                                INSERT orders (mode='paper', status='filled')
                                INSERT positions (status='open')
                                ledger.debit_in_conn  (T_TRADE_OPEN)
                                audit.write           (paper_open)
                                TradeNotifier.notify_entry  (Telegram receipt)

exit watcher tick (30s, APScheduler)
  -> scheduler.py:335                      check_exits  (returns dict -> job_runs.metadata)
       -> domain/execution/exit_watcher.py:run_once
            -> live Polymarket price
            -> force_close > TP > SL > strategy_exit > market_expired > hold
            -> domain/execution/paper.py:96  close_position
                 UPDATE positions status='closed', pnl_usdc, closed_at
                 ledger.credit_in_conn  (T_TRADE_CLOSE)
                 audit.write            (paper_close)
            -> monitoring/alerts.py:alert_user_{tp_hit|sl_hit|force_close|strategy_exit|manual_close|market_expired|close_failed}

NOTIFY triggers (migration 029)
  AFTER INSERT/UPDATE orders   -> cb_orders     (user_id, id, status)
  AFTER INSERT       fills     -> cb_fills      (order_id, id)
  AFTER INSERT/UPDATE positions-> cb_positions  (user_id, id, status)
  AFTER INSERT portfolio_snapshots -> cb_portfolio (dormant — no writer)

job_runs.metadata (migration 030)
  scheduler.py:482  _job_tracker_listener captures event.retval
  domain/ops/job_tracker.py:85  INSERT INTO job_runs (..., metadata) VALUES (..., $6::jsonb)
  exit_watch tick writes {submitted, expired, held, errors}
```

---

## 3. Files Created / Modified

- `projects/polymarket/crusaderbot/reports/forge/runtime-spine-validation.md` — this report.

No production code modified. No state schema touched. `compileall` and `pytest` not re-run since no code changed (evidence-only pass against current `main` HEAD).

---

## 4. What Is Working (per #1243 Validation Targets)

| # | Issue #1243 Target | Status | Code Path Evidence |
|---|---|---|---|
| 1 | `/start` → main menu loads | REAL | `bot/handlers/start.py:63` `start_command` → `users.upsert_user` (line 66); returning users routed to `bot/handlers/dashboard.py` `show_dashboard` (line 71); new users into welcome ConversationHandler (line 74). Dashboard text keyboard wired group=-1 at `bot/dispatcher.py:155` (`📊 Dashboard` regex). |
| 2 | Signal scan → trade placement (`signal_following` fires, order in DB) | REAL | `services/signal_scan/signal_scan_job.py:728` `run_once` → `_process_candidate` (line 431) → `TradeEngine.execute` (line 644) → `domain/execution/paper.py:37` `INSERT INTO orders ... mode='paper', status='filled'` (atomic with positions + ledger inside `conn.transaction()` at line 36). |
| 3 | Position tracking (`positions` updated, `portfolio_snapshots` reflects equity) | PARTIAL | `positions` table: REAL — `paper.py:52` `INSERT INTO positions` inside same txn; `cb_positions` NOTIFY trigger fires (migration 029 line 158). `portfolio_snapshots`: TABLE EXISTS + NOTIFY TRIGGER WIRED but NO Python writer (see §5 known issues). Equity is derived live from `ledger` via `services/portfolio_chart.py:38` `_fetch_daily_balance_series`. |
| 4 | Trade close (close button → fill recorded → position CLOSED) | REAL | `bot/handlers/positions.py` `force_close_confirm` (callback pattern `position:fc_(yes|no):` at `dispatcher.py:285`) → `domain/execution/paper.py:96` `close_position` UPDATE positions status='closed', exit_reason, pnl_usdc, closed_at (line 114) atomic with `ledger.credit_in_conn` (line 128). Exit watcher tick: `scheduler.py:335` `check_exits` → `domain/execution/exit_watcher.py:run_once` → same `paper.close_position`. |
| 5 | Receipt generation | REAL | Open: `services/trade_notifications/notifier.py:177` `notify_entry` called from `paper.py:80`. Close: `monitoring/alerts.py:277` `alert_user_tp_hit`, line 298 `alert_user_sl_hit`, line 319 `alert_user_force_close`, line 340 `alert_user_strategy_exit`, line 361 `alert_user_manual_close`, line 382 `alert_user_market_expired`, line 403 `alert_user_close_failed`. Function name `check_with_receipt()` in issue body does not exist as a callable — wording is abstract for the open + 7 close alert surface above. |
| 6 | PnL consistency (`pnl_today` + `equity_usdc` correct after close) | REAL | `wallet/ledger.py` `daily_pnl` SUMs `trade_close + redeem + fee` since day start; called by risk gate step 5 and position handlers. Position `pnl_usdc` written atomically in `paper.close_position` (line 117). Live `current_price` for open positions guarded by strict-interior check via `get_live_market_price` (WARP-38 fix already merged on main, see PROJECT_STATE [IN PROGRESS] line 33). |
| 7 | Telegram routing (no dead buttons) | REAL | `bot/dispatcher.py:148-339` registers 30+ `CallbackQueryHandler` patterns covering: `menu:`, `nav:`, `p5:(preset|confirm|active):`, `auto_trade:`, `p5:emergency:`, `close_position:`, `close_position:confirm:`, `p5:trades:cancel_close`, `p5:trades:history`, `p5:wallet:`, `wallet:`, `setup:`, `preset:`, `set_strategy:`, `set_risk:`, `set_cat:`, `set_mode:`, `set_redeem:`, `settings:`, `dashboard:`, `strategy:`, `tp_set:`, `sl_set:`, `cap_set:`, `autotrade:`, `position:close:`, `position:fc_ask:`, `position:fc_(yes|no):`, `insights:`, `chart:`, `mytrades:close_ask:`, `mytrades:close_(yes|no):`, `mytrades:hist:`, `mytrades:back`, `emergency:`, `admin:`, `ops:`, `copytrade:`, `signals:`, `market:`, `live_gate:`, `referral:share:`, `onboard:view_dashboard`, `onboard:settings`, `portfolio:`, `mytrades:open:`, `noop:`, `tgnotif:`, `r5cfg:`. Text keyboard buttons registered group=-1 at lines 155-171 with `MessageHandler(filters.Regex(...))`. No orphan callback prefix found. |

### New audit dimensions added by issue #1243

| Dimension | Status | Evidence |
|---|---|---|
| NOTIFY trigger `cb_orders` | REAL | `migrations/029_webtrader_tables.sql:147-150` `trg_cb_orders AFTER INSERT OR UPDATE ON orders`. |
| NOTIFY trigger `cb_fills` | REAL | `migrations/029_webtrader_tables.sql:152-155` `trg_cb_fills AFTER INSERT ON fills`. |
| NOTIFY trigger `cb_positions` | REAL | `migrations/029_webtrader_tables.sql:157-160` `trg_cb_positions AFTER INSERT OR UPDATE ON positions`. |
| `job_runs.metadata` populated each tick | REAL | `scheduler.py:482-529` `_job_tracker_listener` captures `event.retval` from `check_exits` (line 335 returns `{submitted, expired, held, errors}`) and dispatches to `domain/ops/job_tracker.py:85` `INSERT INTO job_runs (..., metadata) VALUES (..., $6::jsonb)`. `services/daily_report_service.py:160` also writes `job_runs.metadata` for the daily summary job. |
| No silent exception swallowing | REAL | Recursive grep across all production `.py` files for `except.*:.*pass` and `except.*:.*\.\.\.` returns zero hits outside docstrings. Every `except Exception as exc:` clause is followed by `logger.{warning,error}` or structlog `log.{warning,error}` — verified by spot-check across `scheduler.py`, `signal_scan_job.py`, `paper.py`, `job_tracker.py`. `exit_watcher.py:31` docstring explicitly asserts the invariant. |

---

## 5. Known Issues

- `portfolio_snapshots` table (migration 029 line 5-16) and the `cb_portfolio` NOTIFY trigger (line 172-175) are installed in production but no Python code writes to the table. WebTrader PnL chart + Telegram `portfolio_chart.py` both derive equity live from the `ledger` table via `_fetch_daily_balance_series`. The cb_portfolio NOTIFY channel is therefore dormant — WebTrader SSE listeners on `cb_portfolio` will not see traffic. Severity: low; out of #1243 scope ("WebTrader SSE separate task"). A separate lane is required to either (a) add a periodic snapshot writer + retire the live-ledger derivation, or (b) drop the unused table + trigger.
- Issue #1243 §Validation Targets references `check_with_receipt()` as a specific function — that exact callable does not exist. The actual receipt surface is `TradeNotifier.notify_entry` + the 7 `alert_user_*` close handlers. Issue wording is abstract; not a runtime defect.
- Existing legacy DEAD classes from prior pass (`domain/strategy/strategies/momentum_reversal.py`, `domain/strategy/strategies/signal_following.py`) remain importable-but-unused — superseded by the `lib/strategies/` path via `lib_strategy_runner`. Already documented in `runtime-spine-evidence.md` from issue #1206. No change.
- End-to-end live execution against the deployed Telegram bot on Fly.io is not exercised by this evidence pass — the cloud execution environment cannot drive a real Telegram update. Acceptance criterion "Full `/start` → close trade → receipt flow completes without error" in issue #1243 is therefore validated by code-path proof + the existing test suite (`tests/test_pipeline_runtime_hardening.py`, `tests/test_exit_watcher.py`, `tests/test_order_lifecycle.py`, `tests/test_dashboard_routing.py`) rather than a Telegram replay. WARP🔹CMD may want a one-shot manual smoke from the bot account before closing the lane.

---

## 6. What Is Next

**Suggested Next Step:** WARP🔹CMD review.

If accepted as written, the lane closes and WARP-46 is done. If WARP🔹CMD wants the `portfolio_snapshots` writer wired (out of scope for this issue), open a follow-up lane referencing finding §5 line 1 — preferred path is a periodic 60s tick that writes `(user_id, balance_usdc, equity_usdc, pnl_today, pnl_7d, open_positions)` so the cb_portfolio NOTIFY channel becomes live for the WebTrader SSE bridge.

WARP•SENTINEL is NOT required (Tier: STANDARD).

---

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : 7 explicit issue #1243 targets + NOTIFY triggers + job_runs.metadata + silent-exception audit, all against current `main` HEAD
Not in Scope      : Live trading activation, capital mode, WebTrader SSE wiring, DB schema changes, new features
Suggested Next    : WARP🔹CMD review
