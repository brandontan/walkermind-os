# WARP•SENTINEL Report — Operator Control Panel (async)

- Branch: `WARP/operator-control-panel-async`
- Source PR: #1310
- Source report: `projects/polymarket/crusaderbot/reports/forge/operator-control-panel-async.md`
- Validation Tier: **MAJOR**
- Claim Level: **NARROW INTEGRATION**
- Environment: `dev` (build container — no live DB; asyncpg absent + cryptography Rust panic)
- Verdict: **CONDITIONAL** — Score 81/100, 0 critical

---

## TEST PLAN

- Phase 0: report/state/structure pre-checks.
- Phase 1: functional — `/panel` command, callback routing, render helpers.
- Phase 2: pipeline — `run_signal_scan` metrics → listener → `job_runs.metadata` → `fetch_latest`.
- Phase 3: failure modes — DB / kill-switch / job_tracker read failure on every panel path.
- Phase 4: async safety — no threading, single event loop, additive counters.
- Phase 5: risk — guards untouched, paper-only, kill-switch single path, operator gating.
- Phase 6–8: latency / infra / Telegram — static review only (no live runtime here).

Live-DB end-to-end assertions (actual row contents, real state flips, live render) were
**NOT executable** in this container — deferred to operator pre-merge run.

---

## PHASE 0 — PRE-TEST

- Source report present, correct path/naming, all 6 sections + metadata: **PASS**.
- `PROJECT_STATE.md` updated by FORGE (IN PROGRESS + NEXT PRIORITY WARP-OPC entries): **PASS**.
- No `phase*/` folders introduced; domain structure intact: **PASS**.
- Implementation evidence exists for every claimed integration point: **PASS**.

---

## FINDINGS

Part A — runtime-proof instrumentation:

- `scheduler.run_signal_scan()` returns the metrics dict with all required keys
  (`scheduler.py:422-433`): mode, live_trading, strategies_loaded, users_scanned,
  markets_seen, candidates_emitted, risk_approved, risk_rejected, paper_orders_created,
  positions_created, errors. **PASS**.
- Persistence path verified: `_job_tracker_listener` captures any dict `retval`
  (`scheduler.py:732-736`) → `record_job_event` writes `json.dumps(metadata)::jsonb`
  into `job_runs.metadata` (`domain/ops/job_tracker.py` INSERT). Same path `check_exits`
  already uses. **PASS**.
- Job ids `signal_scan` and `portfolio_snapshots` (setup_scheduler) match the
  `fetch_latest()` query argument. **PASS**.
- `snapshot_portfolios()` returns `{"snapshots_written": N}` (`scheduler.py:561-570`),
  captured by the same listener. **PASS**.
- `markets_seen` uses a walrus truthiness guard
  `if (m_id := getattr(cand, "market_id", None)):` (`scheduler.py`) — None / empty-string /
  falsy IDs are excluded before `set.add`. **PASS** (addresses the invalid-ID concern).
- `_process_candidate` returns outcome strings (`skipped`/`rejected`/`executed`/`error`);
  per-candidate try/except isolation preserved (one bad candidate cannot abort a tick).
  **PASS**. Return type change `None → dict` is backward-compatible (listener `isinstance`
  guards the dict).

Part B — operator control panel:

- `/panel` and `panel:` callback both gate on `_is_operator` (== `OPERATOR_CHAT_ID`,
  `bot/handlers/admin.py:46-49`); non-operator → `_reject_silently`
  (no reply on command; silent `callback_query.answer()` on callback,
  `admin.py:52-60`). Non-operator silent reject: **PASS**.
- Start/Stop/Lock delegate to `_apply_killswitch_action`
  (`admin.py:709`): start→`ks_reset`, stop→`ks_execute` (unified kill-switch executor),
  lock→`ops_kill_switch.set_active`; each writes `audit.write(kill_switch_{action})`
  and the kill-switch path writes `kill_switch_history`. **PASS** (no new control logic).
- Status reuses `_collect_dashboard_snapshot` + `_render_dashboard`; Stats reads
  `job_tracker.fetch_latest` for both job ids and renders read-only. **PASS**.
- Guards untouched / paper-only: panel only **reads** `ENABLE_LIVE_TRADING`,
  `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`; `config.resolve_trading_mode()`
  is read-only; no activation gate is written anywhere in the diff. **PASS**.
- No threading, no SQLite, no fly.toml / Dockerfile / migration change in PR #1310
  (the fly.toml/migration entries in the raw diffstat are main-divergence, not PR files).
  **PASS**.

Failure modes (extra review focus #1 — DB/kill-switch read failure):

- `panel_command`, `_render_root`, `_edit`, and `panel:stats` each wrap the DB /
  kill-switch / job_tracker read in try/except, log via `logger.error`, and degrade
  gracefully (`active=False`, `"❓ unknown (DB unreachable)"`, `"N/A — data not
  available"`). No silent failure; panel still opens during a DB hiccup. **PASS**.

---

## CRITICAL ISSUES

None found.

---

## MEDIUM / LOW FINDINGS

- **M-1 (extra review focus #2 — overclaim):** `paper_orders_created` and
  `positions_created` are both assigned the same `orders_created` counter
  (`scheduler.py:430-431`), which increments solely when `router_execute()` does not
  raise (`_process_candidate` returns `"executed"`). They are **not** verified against
  actual `orders` / `positions` DB rows, and one router success is reported as both one
  order **and** one position. The label "positions_created" therefore asserts a DB-row
  outcome it does not prove. Recommend deriving from confirmed DB writes, or renaming to
  `router_executed` / documenting it as an execution-attempt proxy. Non-blocking
  (observational metric only; no trading-path effect).
- **L-1:** `live_trading` field is the raw `get_settings().ENABLE_LIVE_TRADING` flag, not
  the full three-guard `resolve_trading_mode()` result that drives `mode`. Consistent in
  practice (mode=live requires the flag true) but the two fields derive from different
  predicates. Cosmetic.
- **L-2:** Stats reflects the latest tick only (point-in-time), not an aggregate — as the
  FORGE report already notes. Expected by design.

---

## STABILITY SCORE

| Dimension | Weight | Score | Note |
|---|---|---|---|
| Architecture | 20 | 20 | Additive; reuses audited kill-switch / dashboard / job_tracker paths |
| Functional | 20 | 12 | Code paths correct; live runtime not executable here |
| Failure modes | 20 | 16 | All panel reads guarded + logged; no silent fail |
| Risk | 20 | 20 | Guards untouched, paper-only, kill-switch single path, operator-gated |
| Infra + Telegram | 10 | 7 | No fly/docker/migration change; TG wiring correct; not live-exercised |
| Latency | 10 | 6 | In-memory counters, negligible overhead; not measured live |
| **Total** | **100** | **81** | |

---

## GO-LIVE STATUS

**CONDITIONAL.** The change is additive, behaviour-preserving, and safety-clean at the
code level: live-trading guards are never written, the kill switch remains the single
control path, operator gating and silent reject are correct, the metrics-persistence
chain is sound, and every panel read fails safe. No critical issue. It is **not APPROVED**
because the MAJOR validation target is explicitly a live-DB end-to-end proof that cannot
be run in this container, and M-1 (`positions_created` overclaim) should be acknowledged
before merge.

---

## FIX RECOMMENDATIONS (priority order)

1. (M-1) Derive `positions_created` from a confirmed DB position-row write, or rename to an
   execution-attempt proxy so the metric does not overclaim DB-row proof.
2. Operator must run the live-DB gate before merge: seed `auto_trade_on=TRUE, paused=FALSE`,
   let `signal_scan` tick, assert latest `job_runs` `signal_scan` metadata carries
   `mode=paper` / `live_trading=false` + the counters, and `portfolio_snapshots` metadata
   carries `snapshots_written`.
3. In Telegram (operator): confirm `/panel` Start/Stop flip `system_settings.kill_switch_active`
   + write `kill_switch_history`; Status/Stats render live values; a non-operator hits the
   silent-reject path; `ENABLE_LIVE_TRADING` stays `false` throughout.
4. (L-1) Optionally align `live_trading` with `resolve_trading_mode()` for single-predicate
   consistency.

---

## TELEGRAM PREVIEW

```
🎛 Operator Control Panel

Mode: PAPER
State: ▶️ RUNNING

Start / Stop the auto-trade engine, or open Status / Stats below.

[▶️ Start]   [⏹ Stop]
[📊 Status]  [📈 Stats]
[⚙️ Settings] [❓ Help]
[🔒 Lock (force users off)]
[🔄 Refresh]
```

Stats view (latest `signal_scan` tick): mode, live_trading, strategies_loaded, users_scanned,
markets_seen, candidates_emitted, risk_approved/rejected, paper_orders_created,
positions_created, errors, snapshots_written. Non-operator `/panel` → silent no-op.
