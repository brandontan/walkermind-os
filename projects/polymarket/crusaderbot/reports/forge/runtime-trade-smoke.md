# WARP•FORGE REPORT — runtime-trade-smoke

**Branch:** WARP/runtime-trade-smoke
**Date:** 2026-05-23 17:49 Asia/Jakarta
**Linear:** WARP-43 — Runtime Trade Smoke (Engine Proof, Lane 1)
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** scan_runs telemetry table + structured log events (strategies_loaded, scan_input, strategy_run, risk_gate, paper_execution) + GET /admin/scan/last + GET /admin/scan/list + startup loud-failure guard
**Not in Scope:** live execution path, strategy behavior changes, risk gate step composition, WebTrader frontend, Telegram bot copy, snapshots_written tracking (positions not closed in smoke path)

---

## 1. What Was Built

Six scopes of observability instrumentation proving one full paper-trading lifecycle is end-to-end visible:

**A. Strategy load proof** (`main.py` lifespan)
- On startup, imports StrategyRegistry + ENABLED_STRATEGIES + DEFERRED_STRATEGIES
- Logs `event=strategies_loaded` with count, domain_count, lib_count, names, enabled_lib
- If `_total_strategies == 0` → raises `RuntimeError` (loud startup failure, process does not start)

**B. Feed/market input proof** (`signal_scan_job.py` `run_once`)
- Each scan tick logs `event=scan_input` with scan_run_id, markets_seen, markets_eligible, users_evaluated, skip_breakdown JSON
- Per-skip reasons accumulated in `ScanTelemetry.skip_breakdown` via `record_skip(reason)`

**C. Candidate proof** (`signal_scan_job.py` strategy loops)
- Each strategy logs `event=strategy_run` with strategy name, candidates_emitted, zero_reason
- `zero_reason_breakdown` populated in ScanTelemetry when candidates_emitted == 0

**D. Risk gate proof** (`signal_scan_job.py` `_process_candidate`)
- Rejection: logs `event=risk_gate`, calls `telemetry.record_rejection(result.failed_gate_step, result.rejection_reason)`
- Approval: logs `event=paper_execution` with order_id, position_id, market_id, side, size_usdc, price, strategy_type
- All counts aggregated into `ScanTelemetry` and written to `scan_runs` table at tick end

**E. Paper execution proof** (`signal_scan_job.py` `_process_candidate`)
- Accepted outcome: `logger.info("paper_execution", event="paper_execution", order_id=..., position_id=..., market_id=..., ...)` 
- `telemetry.record_approved()` increments `risk_approved`, `paper_orders_created`, `positions_created`

**F. Runtime visibility** (`api/admin.py` + `migrations/048_scan_run_telemetry.sql`)
- `GET /admin/scan/last` — full telemetry snapshot of the most recent scan tick
- `GET /admin/scan/list?limit=N` — headline counts for last N ticks (default 20, max 100)
- `scan_runs` table: one row per tick, all JSONB breakdown columns, indexed on `started_at DESC`

---

## 2. Current System Architecture

```
STARTUP
  main.py (lifespan)
    └─ bootstrap_default_strategies() + seed_defaults()
    └─ StrategyRegistry.list_available() + ENABLED_STRATEGIES + DEFERRED_STRATEGIES
    └─ if total == 0 → raise RuntimeError [LOUD FAIL]
    └─ log event=strategies_loaded

SCAN TICK (APScheduler → signal_scan_job.run_once)
  run_once()
    ├─ _insert_scan_run(run_id, ...)        [DB row opened]
    ├─ log event=signal_scan_job_started
    ├─ _load_enrolled_users()
    │     └─ if empty → _finish_scan_run() → return
    ├─ _fetch_markets_for_lib_strategies()
    ├─ tel = ScanTelemetry()
    ├─ per lib strategy:
    │     └─ run_lib_strategy() → candidates
    │     └─ log event=strategy_run
    │     └─ tel.candidates_emitted += len(cands)
    │     └─ tel.record_zero_reason() if 0
    │     └─ _process_candidate(row, cand, tel) for each candidate
    ├─ confluence_scalper path (same pattern)
    ├─ signal feed path (same pattern)
    ├─ log event=scan_input (summary)
    └─ _finish_scan_run(run_id, tel)        [DB row closed]

_process_candidate(row, cand, tel)
    ├─ kill_switch check → tel.record_skip("skipped_kill_switch")
    ├─ market sync check → tel.record_skip("skipped_market_not_synced")
    ├─ dedup check → tel.record_skip("skipped_dedup")
    ├─ open position check → tel.record_skip("skipped_open_position_exists")
    ├─ price drift check → tel.record_skip("skipped_price_drifted")
    ├─ liquidity check → tel.record_skip("skipped_liquidity")
    ├─ signal staleness check → tel.record_skip("skipped_signal_stale")
    ├─ risk gate → rejected: tel.record_rejection(step, reason)
    └─ accepted: tel.record_approved() + log event=paper_execution

ADMIN API
  GET /admin/scan/last  → scan_runs ORDER BY started_at DESC LIMIT 1
  GET /admin/scan/list  → scan_runs ORDER BY started_at DESC LIMIT N

TELEMETRY TABLE (PostgreSQL)
  scan_runs: id, started_at, finished_at, users_evaluated, markets_seen,
             markets_eligible, strategies_loaded, candidates_emitted,
             risk_approved, risk_rejected, paper_orders_created,
             positions_created, snapshots_written, skip_breakdown JSONB,
             zero_reason_breakdown JSONB, rejection_breakdown JSONB,
             mode VARCHAR(16), live_trading BOOLEAN
```

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/migrations/048_scan_run_telemetry.sql` — additive/idempotent migration; scan_runs table + index
- `projects/polymarket/crusaderbot/tests/test_runtime_trade_smoke.py` — hermetic smoke test (~280 lines, 4 test classes, 14 test cases)
- `projects/polymarket/crusaderbot/reports/forge/runtime-trade-smoke.md` — this file

**Modified:**
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — ScanTelemetry dataclass, _insert_scan_run/_finish_scan_run helpers, _process_candidate telemetry args + skip/rejection/approval logging, run_once() telemetry wiring
- `projects/polymarket/crusaderbot/api/admin.py` — added GET /admin/scan/last + GET /admin/scan/list endpoints
- `projects/polymarket/crusaderbot/main.py` — startup strategy count + loud fail RuntimeError + event=strategies_loaded log

---

## 4. What Is Working

- `ScanTelemetry` dataclass: initialises to zero; record_skip/record_rejection/record_approved/record_zero_reason accumulate correctly
- All 7 skip paths in `_process_candidate` call `telemetry.record_skip(reason)`
- Rejection path calls `telemetry.record_rejection(result.failed_gate_step, result.rejection_reason)` — uses existing `GateResult` fields without gate.py changes
- Accepted path emits `event=paper_execution` structured log with order_id, position_id, market_id, side, size_usdc, price
- `_insert_scan_run` opens a DB row at tick start; `_finish_scan_run` closes it with all accumulated counts — called on ALL early-return paths (user load error, no enrolled users)
- `GET /admin/scan/last` returns full observability snapshot with all breakdown JSONBs
- `GET /admin/scan/list` returns headline counts for last N ticks, limit clamped 1–100
- Startup loud-failure: if zero strategies loaded → `raise RuntimeError` prevents process boot
- `event=strategies_loaded` log includes count, domain names, enabled lib names
- All 4 production files pass `py_compile` check
- Hermetic tests cover: telemetry unit state, _process_candidate accepted/rejected/skip paths, run_once scan_run DB write on approval and no-users, startup RuntimeError guard

---

## 5. Known Issues

- `snapshots_written` always 0 in scan_runs — snapshots are written on position close (redemption path), not on open; tracking would require hooking the redemption scheduler. Deferred; field exists for future use.
- `zero_reason_breakdown` for signal feed candidates uses the generic reason `"filter_or_no_match"` — granular per-signal reasons would require changes to the signal feed reader. Deferred; current breakdown is sufficient for smoke proof.
- Tests use `projects.polymarket.crusaderbot.*` import paths; running with `python -m pytest` from repo root requires PYTHONPATH to include the repo root. This is consistent with existing test conventions.

---

## 6. What Is Next

- WARP🔹CMD: review PR, decide merge
- Post-merge: run `048_scan_run_telemetry.sql` migration against staging DB
- Verify `GET /admin/scan/last` returns non-null data after one scheduler tick in staging
- If 0 candidates still observed in staging: escalate to WARP-44 (strategy debug lane) using skip_breakdown + zero_reason_breakdown as evidence
- Future: wire `snapshots_written` to redemption scheduler callback
- Future: per-signal zero_reason granularity in signal feed reader

---

**Suggested Next Step:** WARP🔹CMD review of WARP/runtime-trade-smoke. Apply migration 048 to staging. Observe one full scan tick via `GET /admin/scan/last` to confirm scan_runs row is written with non-zero fields.
