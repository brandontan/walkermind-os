# WARP•FORGE Report — Operator Control Panel (async)

- Branch: `WARP/operator-control-panel-async`
- Validation Tier: **MAJOR** (touches the signal-scan pipeline + Telegram start/stop control)
- Claim Level: **NARROW INTEGRATION** (operator panel UI/API + additive scan instrumentation)
- Validation Target: `/panel` operator surface + `run_signal_scan` metrics + `job_tracker.fetch_latest`
- Not in Scope: live trading (guards stay OFF), threading, SQLite paper trader, fly.toml/Dockerfile, per-user UX, new strategies, execution/risk-gate logic.
- Suggested Next Step: WARP•SENTINEL MAJOR validation against a live DB (runtime proof was not producible in this build container).

---

## 1. What was built

Adapt-intent delivery of the handoff "convert crusaderbot into a long-running
background process controlled via Telegram (like polymarket-arbibot)". CrusaderBot is
**already** a long-running async service (FastAPI + python-telegram-bot + APScheduler +
Postgres) with Start/Stop (kill switch), Status, Stats (`/jobs`), and `OPERATOR_CHAT_ID`
gating. The arbibot mechanics (threading daemon + asyncio bridge, SQLite `paper_trader.py`,
fly.toml without `[http_service]`) conflict with this repo's hard rules (asyncio-only) and
its existing Postgres paper trading + health-checked deployment, so they were **rejected**
per WARP🔹CMD direction.

Two parts were built:

- **Part A — runtime-proof instrumentation (additive, behaviour-preserving).** The scan
  job now emits durable pipeline metrics so the proof
  `scan → candidate → risk gate → paper order → position → snapshot` is queryable.
- **Part B — consolidated operator control panel (`/panel`).** A single operator-only
  inline-keyboard surface composing the controls/views that already existed piecemeal.

## 2. Current system architecture

```text
APScheduler (single async loop)
  signal_scan tick ── run_signal_scan() ──► returns metrics dict
                                              │
  portfolio_snapshots tick ── snapshot_portfolios() ─► {"snapshots_written": N}
                                              │
        _job_tracker_listener (EVENT_JOB_EXECUTED) ──► job_runs.metadata (JSONB)
                                              │
Telegram (python-telegram-bot Application)    │ read
  /panel ─► operator_panel.panel_command ─────┘
  panel: ─► operator_panel.panel_callback
              Start/Stop/Lock ─► admin._apply_killswitch_action ─► domain/ops/kill_switch
              Status          ─► admin._collect_dashboard_snapshot + _render_dashboard
              Stats           ─► job_tracker.fetch_latest("signal_scan" / "portfolio_snapshots")
              Settings/Help   ─► read-only get_settings() / static text
  gate: admin._is_operator (OPERATOR_CHAT_ID)
```

No new threads, no new process, no new datastore. The kill switch remains the single
source of truth enforced at the risk gate; `/panel` is a view/controller over it.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/scheduler.py` — added `_resolve_mode()`; `run_signal_scan()` now returns a metrics dict (mode, live_trading, strategies_loaded, users_scanned, markets_seen, candidates_emitted, risk_approved, risk_rejected, paper_orders_created, positions_created, errors); `_process_candidate()` now returns outcome strings (`skipped`/`rejected`/`executed`/`error`). `snapshot_portfolios()` already returned `{"snapshots_written": N}` — unchanged.
- `projects/polymarket/crusaderbot/domain/ops/job_tracker.py` — added `fetch_latest(job_id)` returning the most recent `job_runs` row incl. `metadata`.
- `projects/polymarket/crusaderbot/bot/keyboards/admin.py` — added `operator_panel_keyboard(kill_active)`.
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — import `operator_panel`; register `/panel` command + `panel:` CallbackQueryHandler.

Created:
- `projects/polymarket/crusaderbot/bot/handlers/operator_panel.py` — `/panel` command + `panel:` callback (Start/Stop/Lock/Status/Stats/Settings/Help/Refresh), operator-gated, PAPER-mode metadata decode helper.

State + report:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` (Last Updated, IN PROGRESS, NEXT PRIORITY)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` (lane entry)
- `projects/polymarket/crusaderbot/reports/forge/operator-control-panel-async.md` (this file)

## 4. What is working

- `python -m py_compile` clean on all 5 changed/new Python files.
- Instrumentation is purely additive: the scan/trade/risk control flow is unchanged; only
  return values were added. `run_signal_scan`'s dict is captured by the pre-existing
  `_job_tracker_listener` exactly like `check_exits`'s dict already is.
- `_process_candidate` outcome strings map cleanly to the run-level counters; the existing
  per-candidate `try/except` isolation is preserved (one bad candidate cannot abort a tick).
- Operator panel composes existing, audited control paths (`_apply_killswitch_action`,
  `_collect_dashboard_snapshot`, `job_tracker`) rather than introducing new control logic.
- No existing test targets `scheduler.run_signal_scan`/`scheduler._process_candidate`
  (the `_process_candidate` covered by tests is `services/signal_scan/signal_scan_job.py`,
  a different function), so the additive return change does not break existing tests.

## 5. Known issues

- **Runtime/integration proof NOT produced in this container.** `asyncpg` is not installed
  and `cryptography`'s Rust binding panics here (`pyo3_runtime.PanicException`), so the
  telegram/web3 import chain cannot load and the app cannot boot or run pytest in this
  environment (same posture as WARP-58/59/60/61). End-to-end verification is handed to
  WARP•SENTINEL.
- `job_runs.metadata` is JSONB and no asyncpg JSON codec is registered, so it returns as a
  `str`; the panel decodes it defensively via `_coerce_metadata` (dict passthrough / json.loads /
  `{}`). SENTINEL should confirm the decode against a live row.
- Stats reflects the **latest** `signal_scan` tick only (point-in-time), not an aggregate.

## 6. What is next

- WARP•SENTINEL MAJOR validation against a live DB:
  1. Seed a user `auto_trade_on=TRUE, paused=FALSE`; let `signal_scan` tick.
  2. Assert latest `job_runs` `signal_scan` `metadata` has `mode=paper`, `live_trading=false`,
     and the counters; assert `portfolio_snapshots` `metadata` has `snapshots_written`.
  3. As operator: `/panel` → Start/Stop flips `system_settings.kill_switch_active` +
     `kill_switch_history`; Status/Stats render live values; non-operator hits silent reject.
  4. Confirm `ENABLE_LIVE_TRADING` stays `false` throughout.
- On approval: WARP🔹CMD merge decision + Fly.io redeploy (no migration required).
