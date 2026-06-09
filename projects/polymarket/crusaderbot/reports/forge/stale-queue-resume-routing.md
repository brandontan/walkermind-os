# WARP-91 — Stale-Queue Resume Routing Fix

Branch: WARP/stale-queue-resume-routing
Role: WARP•FORGE
Validation Tier: MAJOR (changes execution routing on the crash-recovery resume path)
Claim Level: NARROW INTEGRATION (single resume path in signal_scan_job; hermetic tests, no live/broker exercise)
Validation Target: `services/signal_scan/signal_scan_job.py` stale-queue crash-recovery resume path — strategy resolution for the NULL-fallback default TP/SL and the `strategy_type` passed to `router_execute`.
Not in Scope: strategy `default_tp_sl()` values (1.5/0.5 locked, unchanged); `domain/risk/gate.py` / `slippage_gate.py`; the gate-bypass resume contract / idempotency / size / mode handling; any migration (`execution_queue.strategy_name` already exists, migration 011); `ENABLE_LIVE_TRADING` / `SCORER_ACTIVE` / `ORCHESTRATOR_ACTIVE`.

---

## 1. What was built

The stale-queue crash-recovery resume path in `signal_scan_job.py` re-executes a `status='queued'` `execution_queue` row that a prior tick approved through the risk gate but crashed before `router_execute` completed. That path previously hardcoded the module constant `_STRATEGY_NAME` (`"signal_following"`) for two things:

1. the NULL-fallback default TP/SL resolution (`_strategy_default_tp_sl(_STRATEGY_NAME)`), and
2. the `strategy_type=` argument passed to `router_execute`.

But the resume path also covers `safe_close` and the other candle presets that belong to `late_entry_v3`. Resuming a `late_entry_v3`-origin row as `signal_following` routes it under the wrong strategy and can skip strategy-specific exit / force-exit evaluation. (Gemini flagged this as a PRE-EXISTING issue on the just-merged PR #1705 / WARP-90.)

Change: the resume path now resolves the row's ORIGINATING strategy once and threads it through both consumers, with a backward-compatible fallback for legacy rows.

- `_load_stale_queued_row` SELECT now reads `strategy_name` (read-only SELECT; the column already exists — migration `migrations/011_execution_queue.sql` defines `strategy_name VARCHAR(50) NOT NULL` and `_insert_execution_queue` populates it with `cand.strategy_name`).
- Resume path resolves `_stale_strategy: str = str(stale.get("strategy_name") or _STRATEGY_NAME)` once. A legacy/NULL row missing the field falls back to the historical constant — behaviour-preserving for old rows.
- `_stale_strategy` is now used for: `_strategy_default_tp_sl(_stale_strategy)`, the `strategy_name=...` field in both defensive-fallback `log.warning` calls, and `strategy_type=_stale_strategy` on `router_execute`.

The TP/SL value is unaffected today because both `signal_following` and `late_entry_v3` `default_tp_sl()` return identical `(1.5, 0.5)` — the fix corrects the ROUTING, not the numeric default.

## 2. Current system architecture

DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING (unchanged).

The resume path is the only place `router_execute` is called directly (gate already ran on the original tick; re-running it would self-reject on idempotency / 4h staleness, so the resume intentionally bypasses the gate but re-checks account circuit breakers via `_resume_safety_check`). This lane changes only WHICH strategy that single `router_execute` call (and the NULL-fallback default resolver feeding it) is told the row belongs to — it reads the strategy the originating tick already persisted at INSERT time. No new DB round-trip is added (the value rides the existing stale-row SELECT); gate-bypass semantics, idempotency, size and mode handling are untouched.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py`
  - `_load_stale_queued_row`: added `strategy_name` to the SELECT column list.
  - resume path: resolve `_stale_strategy` once; use it for `_strategy_default_tp_sl(...)`, both defensive-fallback `log.warning` `strategy_name` fields, and `strategy_type=` on `router_execute`.
- `projects/polymarket/crusaderbot/tests/test_signal_scan_job.py`
  - `test_process_candidate_resume_routes_under_original_strategy` (late_entry_v3 row → `strategy_type=late_entry_v3` + NULL-fallback default resolved via `late_entry_v3`).
  - `test_process_candidate_resume_backward_compat_missing_strategy_name` (row with no `strategy_name` → falls back to `_STRATEGY_NAME` = `signal_following`).

State / report:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` (surgical: Last Updated; [COMPLETED] +WARP-91; [NEXT PRIORITY] WARP-91 → SENTINEL-required handoff).
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` (append-only WARP-91 entry).
- `projects/polymarket/crusaderbot/reports/forge/stale-queue-resume-routing.md` (this report).

## 4. What is working

- `pytest projects/polymarket/crusaderbot/tests/ -q`: 3105 passed, 15 skipped, 4 failed. The 4 failures are all in `test_clob_pysdk.py` and are PRE-EXISTING / unrelated (`ModuleNotFoundError: No module named 'polymarket'` — missing optional `py-clob-client` module), confirmed by direct run.
- Resume-path subset (`-k resume`): 5 passed (3 existing + 2 new) — the 2 new tests assert the originating strategy reaches both `router_execute` (`strategy_type` kwarg) and `_strategy_default_tp_sl`, plus the legacy fallback to `signal_following`.
- `ruff check .` from repo root: All checks passed.
- Full type hints on changed test helpers (`_fake_default_tp_sl(strategy_name: str) -> tuple[float, float]`) and the new `_stale_strategy: str` resolution.

## 5. Known issues

- None introduced by this lane. The TP/SL numeric default is intentionally unchanged (both strategies = 1.5/0.5); only routing/observability of the originating strategy is corrected.
- Pre-existing (out of scope): `test_clob_pysdk.py` 4 failures from the missing optional `polymarket` module in this environment.

## 6. What is next

- WARP•SENTINEL validation (MAJOR) before merge — this lane changes execution routing.
- Suggested Next Step: WARP•SENTINEL audits the resume path for (a) correct strategy threading to `router_execute` + the default resolver, (b) backward-compat for legacy NULL-strategy rows, and (c) confirmation that gate-bypass / idempotency / size / mode semantics are unchanged. On APPROVED, WARP🔹CMD merges; WARP•R00T may self-merge under full-bypass authority if assigned.

---

Suggested Next Step: hand to WARP•SENTINEL (MAJOR gate) — `reports/sentinel/stale-queue-resume-routing.md`.
