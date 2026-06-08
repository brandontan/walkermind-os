# WARP•FORGE Report — gate-hotpath-db-fix (WARP-89)

Branch: WARP/gate-hotpath-db-fix
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: The per-candidate risk-gate path (`domain/risk/gate.evaluate`) must perform ZERO asyncpg calls for `capital_alloc_pct`; the authoritative CAP% is preloaded once per user per tick into `GateContext` by the signal-scan orchestrator and read from the context.
Not in Scope: `domain/risk/slippage_gate.py` (untouched), `.env`, migrations, copy-trade monitor (event-driven single-signal path, not a per-candidate tick loop — falls back to the one-shot DB loader), `resume_safety_check` crash-recovery path (once-per-queued-row, not per-candidate — retains the one-shot loader), `ENABLE_LIVE_TRADING` / `SCORER_ACTIVE` / `ORCHESTRATOR_ACTIVE` flags.

## 1. What was built

Removed the per-candidate DB read from the risk-gate hot path. Previously `gate.evaluate` called `_capital_alloc_pct(user_id, profile)` at step 8 (capital-deployment cap), which did a `pool.acquire()` + `SELECT capital_alloc_pct FROM user_settings` on EVERY candidate. Under a saturated connection pool this per-candidate acquire caused the Jun-7 prod wedge.

The fix:
- Added optional/defaulted field `capital_alloc_pct: float | None = None` to `GateContext` (same byte-compatible pattern as the WARP-87 `cell`/`orderbook_depth_usdc`/`spread` fields).
- Split the former `_capital_alloc_pct` into a pure resolver `resolve_capital_alloc_pct(raw, profile)` (profile-default fallback + 80% clamp) and a one-shot DB loader `load_user_capital_alloc(user_id, profile)`. Kept `_capital_alloc_pct` as a backward-compatible module-level alias of the loader (used by `resume_safety_check` and as the monkeypatchable fallback name).
- `evaluate` now reads `ctx.capital_alloc_pct` when preloaded (the hot-path case → ZERO DB calls); only when it is `None` (legacy construction sites outside the scan loop) does it fall back to the one-shot loader by the patchable module-level name.
- The signal-scan orchestrator (`_load_enrolled_users`) already loads the per-user settings row ONCE per tick; added `s.capital_alloc_pct AS capital_alloc_pct_raw` (NULL preserved) to that query and resolved it through `resolve_capital_alloc_pct` at both TradeSignal build sites (`_build_trade_signal` and the fast-topup direct build). `TradeSignal` carries the preloaded value and `TradeEngine._build_gate_context` threads it into every per-candidate `GateContext`.

## 2. Current system architecture

Tick (per user): `signal_scan_job._load_enrolled_users` → ONE DB row per user (now includes `capital_alloc_pct_raw`).
Per candidate (hot loop): `_build_trade_signal` resolves the preloaded CAP% (pure, no DB) → `TradeSignal.capital_alloc_pct` → `TradeEngine.execute` → `_build_gate_context` → `GateContext.capital_alloc_pct` → `gate.evaluate` step 8 reads it directly. No asyncpg call for capital_alloc_pct anywhere in the per-candidate path.

Fallback (legacy sites: scheduler.py, complete_set_scan.py, parity.py, copy_trade monitor): `capital_alloc_pct` stays `None` → `evaluate` calls the one-shot loader once — correct behaviour, and those are NOT per-candidate scan loops.

Pipeline order (DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING) unchanged; RISK still runs before EXECUTION.

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/domain/risk/gate.py
- projects/polymarket/crusaderbot/services/trade_engine/engine.py
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py
- projects/polymarket/crusaderbot/tests/test_robustness_gate.py (test stub: thread new field through `_signal_ns`)

Created:
- projects/polymarket/crusaderbot/tests/test_gate_capital_alloc_preload.py
- projects/polymarket/crusaderbot/reports/forge/gate-hotpath-db-fix.md (this report)

## 4. What is working

- New test `test_gate_capital_alloc_preload.py` (4 tests) — drives `evaluate` to step 8 with a preloaded CAP% under a pool whose `acquire()` raises `AssertionError`; the gate rejects/passes step 8 purely from the context with ZERO pool acquire. Also pins the legacy fallback path and the resolver semantics.
- Full suite: `pytest projects/polymarket/crusaderbot/tests/ -q` → 3085 passed, 15 skipped, 4 failed. The 4 failures are `test_clob_pysdk.py` (`ModuleNotFoundError: No module named 'polymarket'`, missing optional SDK) — pre-existing and unrelated to this lane.
- `ruff check .` → All checks passed.
- Existing step-8 gate tests (`test_risk_limit_reconciliation.py`, `test_concurrency_policy.py`, `test_complete_set_scan.py`, `test_robustness_gate.py`) all green.

## 5. Known issues

- 4 unrelated pre-existing failures in `test_clob_pysdk.py` (missing optional `polymarket` module). Not introduced by this lane.
- The fast-topup direct-build path now also preloads CAP% (same resolver) — behaviourally identical to before for non-NULL settings; for legacy NULL rows the gate now resolves to the profile default rather than the row's `us.weight/0.10` sizing fallback. This is the correct/authoritative semantics (matches the previous gate-side DB loader), not a regression.

## 6. What is next

- WARP•SENTINEL MAJOR validation (capital/risk hot path).
- Optional follow-up (separate lane): migrate the copy-trade monitor and the other legacy GateContext construction sites to preload `capital_alloc_pct` so the one-shot fallback loader is never hit at runtime.

Suggested Next Step: WARP•SENTINEL validation of WARP-89 before merge.
