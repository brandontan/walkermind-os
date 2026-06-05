# WARP-76 H2 — Monitoring / alerting + structured trade-event logging

Branch: WARP/monitoring-alerting
Role: WARP•R00T (executing as build/fix)
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: 4 operator Telegram alert types fire; structured log fields (user_id+market_id+rule) on trade events in signal_scan_job + paper.py.
Not in Scope: ENABLE_LIVE_TRADING / USE_REAL_CLOB / live execution path / risk gate.py / DB schema / migrations. No new dependency.
Suggested Next Step: WARP🔹CMD review + merge, then proceed to WARP-76 H3 (feed-loss fail-safe, branch WARP/feed-loss-failsafe).

## 1. What was built

Ground-truth audit first: **3 of the 4 required operator alerts were already
wired by WARP-74** (all fail-soft). This chunk therefore did NOT re-wire them
(that would double-page the operator); instead it verified them, hardened one,
built the genuinely-missing 4th alert, added the structured trade-event log
fields, and added a consolidated WARP-76 test artifact.

### Operator alert inventory (operator channel = OPERATOR_CHAT_ID)

| # | Alert | Status | Site |
|---|---|---|---|
| 1 | Orphan reconcile page | already wired (WARP-74), verified fail-soft | `domain/execution/live_reconcile.py:143` `_page_operator` |
| 2 | Infra-degraded live→paper fallback | already wired (WARP-74), **hardened** (+user_id) | `domain/execution/router.py:124` |
| 3 | Kill-switch trigger | already wired (WARP-74), verified fail-soft | `domain/risk/kill_switch_exec.py:178` |
| 4 | Daily P&L operator summary | **NEW** (built this chunk) | `jobs/operator_daily_summary.py` |

Note: the pre-existing `jobs/daily_pnl_summary.py` is a **per-user** push (each
user gets their own P&L). Alert #4 is a distinct **aggregate** page to the
operator with positions opened/closed/net delta across all paper users — that
operator-facing summary did not exist before.

### Structured logging

`user_id` + `market_id` + `rule` are now present on every trade event:

- `services/signal_scan/signal_scan_job.py` — `_process_candidate` already bound
  `user_id`+`market_id` on its per-candidate logger (line ~2306); added
  `rule=cand.strategy_name`. Because every `scan_outcome` event
  (`accepted` / `rejected` / `skipped_*`) is emitted through that bound logger,
  this single addition covers open / gate_deny / scan_skip in one place.
- `domain/execution/paper.py` — `paper_trade_open` gained `rule=strategy_type`;
  `paper_trade_close` gained `market_id` + `rule`.

## 2. Current system architecture

- Operator alerts all route through `notifications.notify_operator(text, parse_mode=HTML)`
  (retry + plain-text fallback, never raises). Every call site wraps it in a
  try/except so a Telegram outage cannot break the trading/scheduler path.
- New job `operator_daily_summary` registered in `scheduler.py` as a cron at
  23:05 Asia/Jakarta (just after the 23:00 per-user push). Returns its metrics
  dict so the scheduler's `job_runs` listener captures them.
- Structured logs are JSON (structlog) with flat top-level fields; the
  per-candidate bound logger propagates context to all downstream events.

### Alert text examples

```
🚨 KILL SWITCH ACTIVATED
Reason: drawdown>8%
By: risk_monitor

🚨 LIVE INFRA DEGRADED — fell back to PAPER
user=<id>
market=<condition_id>
A live trade could not reach the exchange (CLOB dependency failure) and was routed to paper.
reason: <exc>

🛑 LIVE RECONCILE — UNTRACKED EXPOSURE, TRADING HALTED
<detail>

📊 DAILY PAPER P&L — OPERATOR SUMMARY
opened today: 12
closed today: 9 (W 5 / L 4)
net delta: +$3.21
active users: 4
```

### Structured log examples

```json
{"event":"paper_trade_open","user_id":"u-1","market_id":"0xabc","rule":"flip_hunter","side":"yes","size_usdc":"20","price":0.55}
{"event":"paper_trade_close","user_id":"u-1","market_id":"0xabc","rule":"flip_hunter","position_id":"p-9","exit_reason":"tp","pnl":"3.21"}
{"event":"scan_outcome","outcome":"rejected","user_id":"u-1","market_id":"0xabc","rule":"flip_hunter","side":"yes","strategy":"signal_scan","reason":"liquidity_floor","step":6}
{"event":"scan_outcome","outcome":"skipped_dedup","user_id":"u-1","market_id":"0xabc","rule":"flip_hunter","side":"yes","strategy":"signal_scan"}
```

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/jobs/operator_daily_summary.py`
- `projects/polymarket/crusaderbot/tests/test_warp76_monitoring.py`

Modified:
- `projects/polymarket/crusaderbot/scheduler.py` (import + cron registration)
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` (+`rule` on bound logger)
- `projects/polymarket/crusaderbot/domain/execution/paper.py` (+`rule` open; +`market_id`/`rule` close)
- `projects/polymarket/crusaderbot/domain/execution/router.py` (infra-degraded page +`user_id`)

No change to ENABLE_LIVE_TRADING / USE_REAL_CLOB / gate.py / live exec path / schema.

## 4. What is working

- `tests/test_warp76_monitoring.py`: **12 passed** with full deps (CI condition).
  - Operator daily summary (alert #4): runtime tests — metrics aggregation,
    rendered text, `run_job` pages exactly once with correct content, and a
    notify failure is swallowed (fail-soft).
  - All 4 alert wirings pinned via source-contract (always-run, no imports).
  - Scheduler registration of the new job pinned.
  - Log-field assertions: paper open/close + signal_scan bind carry
    user_id + market_id + rule.
- Existing runtime "fires" coverage for alerts 1–3 still green:
  `test_router_infra_fallback.py`, `test_kill_switch_broker_cancel.py`,
  `test_live_reconcile.py` (24 passed) — router hardening did not regress them.
- `test_signal_scan_job.py` + `test_daily_pnl_summary.py`: 112 passed (incl. the
  scheduler-registration test — new job imports + registers cleanly).
- `ruff check` (project config) on all changed files: clean.

## 5. Known issues

- The runtime operator-summary tests are `pytest.importorskip`-guarded; in a
  dependency-less sandbox lacking `pytest-asyncio` the async cases do not run
  (CI installs the full stack — all 12 pass there). The source-contract tests
  run in every environment.
- Alert #4 aggregates `mode='paper'` only by design; it stays paper-scoped after
  any future live activation.

## 6. What is next

- WARP🔹CMD review + merge of WARP/monitoring-alerting.
- Proceed to WARP-76 H3 — feed-loss fail-safe (branch WARP/feed-loss-failsafe).
  Tier note: H3 must stay a protective halt; if it touches the execution path
  (paper.py/gate.py) it escalates to MAJOR + SENTINEL — will stop and ask CMD.
