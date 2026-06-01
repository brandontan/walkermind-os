# WARP•R00T — risk-path-hardening

**Branch:** `WARP/ROOT/risk-path-hardening`
**Role:** WARP•R00T (system hardening)
**Validation Tier:** MAJOR
**Claim Level:** FULL RUNTIME INTEGRATION
**Validation Target:** the auto-trade risk → execution path — specifically (a) the crash-recovery resume branch in the signal scan loop, (b) strategy routability at risk gate step 4, (c) a boot-time consistency guard between the strategy registry and the risk gate.
**Not in Scope:** the daily-loss / exposure dual-cap reconciliation (C-5/C-6), the concurrency-cap policy decision (C-3), `_process_candidate` decomposition (C-4), and the LIVE live-fire validation (USE_REAL_CLOB end-to-end). Those are separate follow-up lanes.

---

## 1. What was built

Three changes to close two real capital-safety gaps surfaced by the pre-public audit, plus a recurrence guard:

- **C-1 — crash-recovery resume now re-runs the account circuit breakers.**
  The `_process_candidate` stale-queued resume branch (`services/signal_scan/signal_scan_job.py`) previously called `router_execute()` directly, skipping 14 of the 15 risk-gate steps (only the kill switch was re-checked). A user who breached their daily-loss cap, drawdown halt, concurrent-trade limit, exposure cap, or per-user LIVE capital cap *between* the crash and the recovery would have the pending entry executed regardless. A new `domain/risk/gate.py:resume_safety_check()` re-evaluates exactly the capital-circuit-breaker subset (gate steps 0/5/6/7/8/15) before the direct router call. On breach the queued row is marked `failed` (abandoned), never executed.

- **C-2 — weather strategy is now routable at the gate.**
  `domain/risk/constants.py:STRATEGY_AVAILABILITY` had no `"weather"` key. The weather domain strategy emits candidates with `strategy_name="weather"`, so gate step 4 rejected every one as `unknown_strategy` — the entire weather pipeline (migrations 075/076, all 5 exits) converted zero trades. Added the key for all four risk profiles. Weather is in the public LIVE launch scope.

- **MED-2 — boot-time registry↔availability consistency guard.**
  `main.py` lifespan now fails closed at startup if any registered domain strategy is missing from `STRATEGY_AVAILABILITY`, so the C-2 class of bug (a registered strategy silently un-routable at the gate) can never reach production again.

No functional behaviour of the happy path was changed. Risk constants, activation guards, `assert_live_guards`, and the paper/live engines are untouched.

## 2. Current system architecture

Runtime path unchanged except for the resume sub-branch:

```
DATA → STRATEGY (signal_scan_job.run_once)
     → _process_candidate
         ├─ stale-queued crash recovery
         │    ├─ kill_switch (unchanged — leaves row queued for retry)
         │    └─ resume_safety_check  ← NEW: steps 0,5,6,7,8,15
         │         approved → router_execute
         │         blocked  → mark_failed (abandon)
         └─ normal path → TradeEngine.execute → gate.evaluate (15 steps) → router
RISK gate step 4 now recognises strategy_type="weather"
BOOT main.py asserts every registered strategy ∈ STRATEGY_AVAILABILITY
```

`resume_safety_check` reuses the existing gate helpers (`daily_pnl`, `_max_drawdown_breached`, `_open_position_count`, `_open_exposure`, `_open_live_exposure`, `effective_daily_loss`, `profile_or_default`) — no new DB query shapes, no duplicated logic. It intentionally skips staleness (9) and idempotency/dedup (10) — those are precisely the steps that would self-reject a legitimately recovered trade — plus the entry-quality gates (11/12/13/14) that require live market data not persisted on the queue row.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/domain/risk/constants.py` — add `"weather"` to `STRATEGY_AVAILABILITY`.
- `projects/polymarket/crusaderbot/domain/risk/gate.py` — add `resume_safety_check()`.
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — import + invoke `resume_safety_check` in the crash-recovery branch; abandon row on breach.
- `projects/polymarket/crusaderbot/main.py` — boot-time registry↔availability consistency guard.
- `projects/polymarket/crusaderbot/tests/test_signal_scan_job.py` — update resume test for the new gate; add breaker-blocks-resume test.

Created:
- `projects/polymarket/crusaderbot/tests/test_resume_safety_check.py` — 13 hermetic tests.
- `projects/polymarket/crusaderbot/reports/forge/risk-path-hardening.md` — this report.

## 4. What is working

- `pytest tests/test_resume_safety_check.py` — 13/13 pass (balance floor + all five breaker rejections + paper/live cap branches + C-2 + MED-2 invariants).
- `pytest tests/test_signal_scan_job.py` — 85/85 pass (resume happy-path + new breaker-blocks-resume test).
- Full project suite: **2206 passed**. The only non-passes are missing-SDK collection errors in this sandbox (`web3`, `poly_eip712_structs`, `fastapi` were installed where possible; `poly_eip712_structs` is unavailable) — none touch the changed files.
- `py_compile` clean on all changed modules; `ruff check` clean.

## 5. Known issues

- **Not yet addressed (separate lanes, by design):** C-5/C-6 dual daily-loss + exposure caps (profile-based limits are currently shadowed by the −$50 / 0.60 settings caps); C-3 concurrency-cap policy (`MAX_CONCURRENT_TRADES=5` is dead code while profiles use 5/12/20); C-4 `_process_candidate` decomposition.
- The resume path's skipped entry-quality gates (liquidity/edge/impact) are an accepted trade-off documented in the helper docstring — they would require live market data not stored on the queue row, and they are entry-quality, not capital circuit breakers.
- **State drift corrected in this lane:** `WORKTODO.md` C1 line claimed `wallet/withdrawals.py:158 raises NotImplementedError` as a LIVE blocker — code truth is that the on-chain transfer is implemented + gated behind `EXECUTION_PATH_VALIDATED` (no `NotImplementedError` anywhere in the trading/wallet/execution path). Corrected.

## 6. What is next

- **WARP•SENTINEL validation required (MAJOR)** before merge — the change touches the auto-trade execution path.
- Follow-up lane **C-5/C-6** risk-limit reconciliation so LIVE per-profile daily-loss + exposure limits match what the UI promises.
- Follow-up lane **C-3** concurrency policy (WARP🔹CMD decision: enforce global 5, or ratify per-profile 5/12/20 and retire the dead constant).
- Follow-up lane **C-4** decompose `_process_candidate` into composable pipeline-step gates.

---

**Suggested Next Step:** WARP•SENTINEL audit of `WARP/ROOT/risk-path-hardening` (focus: resume_safety_check step coverage + abandon-on-breach + weather routability), then WARP🔹CMD merge decision.
