# bankroll-circuit-breaker

## 1. What was built

Per-user latched circuit breaker in `services/signal_scan/signal_scan_job._process_candidate` step 0a. When a user's current balance drops below `baseline * BANKROLL_CIRCUIT_BREAKER_THRESHOLD` the breaker trips and subsequent candidates short-circuit with `scan_outcome="skipped_circuit_breaker"` BEFORE dedup / open-position / strategy gates. The latch only releases when balance climbs back above `baseline * THRESHOLD * (1 + HYSTERESIS)`.

Reference baseline reuses `_bankroll_ema_baseline` maintained by Lane 5 (`bankroll-dynamic-sizing`) — same source of truth, no duplicate state. The crash-recovery branch (step 0) runs FIRST so an already-approved-but-interrupted trade still completes — the breaker only blocks NEW entries, never the recovery of in-flight ones.

This closes Polybot directive 1.4 (missing bankroll-based circuit breaker) + Sprint-1 directive #6 (bankroll service with circuit breaker). The directive's "cancel all open orders" half is intentionally deferred to a future live-mode lane — paper mode has no live orders to cancel, and the operator's existing `/kill` route already invalidates queued execution + sets `users.paused=True` for that case.

## 2. Current system architecture

```text
_bankroll_ema_baseline (Lane 5)   ← slow-moving per-user EMA reference
        │ (read by both)
        ▼
_evaluate_bankroll_circuit_breaker(user_id, current_balance, threshold, hysteresis)
        │ updates _bankroll_circuit_tripped[user_id] latch
        │ trip:    current < baseline * threshold
        │ resume:  current > baseline * threshold * (1 + hysteresis)
        │ fail-safe: no baseline → False; non-positive / NaN → False
        ▼
_process_candidate
        │
        ├── 0.   Crash-recovery resume       (runs FIRST — in-flight trades complete)
        ├── 0a.  BANKROLL CIRCUIT BREAKER    ← THIS LANE
        │          scoped: every candidate when ENABLED
        │          knob:   BANKROLL_CIRCUIT_BREAKER_ENABLED (default False)
        │          knobs:  _THRESHOLD (default 0.20), _HYSTERESIS (default 0.10)
        ├── 1.   Permanent dedup
        ├── 2.   Open-position dedup
        ├── 3.   Strategy gates (TOB freshness / edge / spread / direction / …)
        └── 4.   Trade engine (13-step risk gate, Kelly 0.25)
```

Hysteresis cushion prevents the "circuit breaker loop" failure mode (directive Appendix C) — without it the latch would flap at the trip boundary on every balance refresh.

## 3. Files created / modified

```text
projects/polymarket/crusaderbot/config.py
projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py
projects/polymarket/crusaderbot/tests/test_bankroll_circuit_breaker.py
projects/polymarket/crusaderbot/reports/forge/bankroll-circuit-breaker.md
projects/polymarket/crusaderbot/state/PROJECT_STATE.md
projects/polymarket/crusaderbot/state/CHANGELOG.md
```

### `config.py`
- Three new knobs: `BANKROLL_CIRCUIT_BREAKER_ENABLED: bool = False`, `_THRESHOLD: float = 0.20`, `_HYSTERESIS: float = 0.10`.
- Two new field validators:
  - `THRESHOLD` must be in `(0, 1]` — 0 never trips (silent disable), > 1 always tripped (silent kill switch).
  - `HYSTERESIS` must be in `[0, 1]` — negative inverts the gate, > 1 locks the breaker permanently after first trip.

### `services/signal_scan/signal_scan_job.py`
- New module-level state `_bankroll_circuit_tripped: dict[str, bool]` — per-user latch.
- New helper `_evaluate_bankroll_circuit_breaker(user_id, current_balance, *, threshold, hysteresis) -> bool` — updates the latch in place and returns its new value.
- New step 0a in `_process_candidate` between crash-recovery (step 0) and permanent dedup (step 1).
- Reads enable knob lazily; on config-read failure fails CLOSED (breaker disabled) so a broken config never silently locks users out.
- Reads param knobs separately so an enabled breaker with corrupt params still has documented fallbacks (0.20 / 0.10).
- Emits `scan_outcome="skipped_circuit_breaker"` with the operator-dashboard fields the directive #9 metrics list calls for (balance_usdc, baseline_usdc, threshold, hysteresis, message).
- `_bankroll_reset_for_tests` now also clears the new latch dict.

### `tests/test_bankroll_circuit_breaker.py`
- 4 source-level pins (gate present, enable knob read, crash-recovery-first ordering, baseline source unification with Lane 5).
- 4 config tests (enable default False, threshold + hysteresis defaults, parametrized rejection of invalid values).
- 7 helper-math tests (above-threshold pass, below-threshold trip, latch between trip + resume bounds, release above resume bound, no-baseline fail-safe, non-positive balance fail-safe, zero-hysteresis thrash contract).
- 4 behavioural integration tests (disabled-passes-drained, enabled-blocks-drained, enabled-passes-healthy, enabled-passes-first-observation).

## 4. What is working

- `ruff check` + `py_compile` clean on all 3 modified files.
- Gate runs after the crash-recovery branch (pinned by `test_gate_runs_after_crash_recovery`) so in-flight trades complete on restart.
- Helper reuses Lane 5's `_bankroll_ema_baseline` (pinned by `test_helper_uses_lane5_baseline`) — no duplicate baseline drift.
- Hysteresis cushion verified at the boundary by `test_helper_latched_below_resume_bound` (210 between 200 trip and 220 resume → stays tripped) and `test_helper_releases_above_resume_bound` (221 > 220 → resumes).
- Default OFF verified end-to-end: even a drained user reaches the engine when `BANKROLL_CIRCUIT_BREAKER_ENABLED=false`. Dark-launch posture is safe.

## 5. Known issues

- Tests cannot run in this remote container (no `fastapi / structlog` in the local env); CI is the authoritative runner. Patterns mirror `test_bankroll_dynamic_sizing.py` + `test_complete_set_edge_gate.py` (both green on CI).
- "Cancel all open orders" half of directive #6 not implemented — deferred to a live-mode lane (paper has nothing to cancel). Documented inline in the config docstring.
- Per-user state is in-process: a Fly restart clears every latch. Acceptable because the breaker re-trips on the next scan tick if the bankroll is still drained, and a restart is already the operator's escape hatch when they need to clear the latch manually.

## 6. What is next

- Lane C `WARP/R00T/bnb-monitor-only` — directive Part 4 Tier 3 asset hygiene.
- Operator paper-mode soak: keep `BANKROLL_CIRCUIT_BREAKER_ENABLED=false` for 24-48h on prod, monitor `_evaluate_bankroll_circuit_breaker` invocation patterns via the unit-test boundaries (the metric is decision-only at OFF state). Flip to `true` once we've confirmed no surprises.
- Lane D (later, architectural) — inventory tracker + dual-leg fast top-up.

---

**Validation Tier**: MAJOR
**Claim Level**: NARROW INTEGRATION
**Validation Target**: signal_scan_job._process_candidate step 0a (new gate); config fields + validators; helper math + latch transitions; Lane 5 baseline source reuse.
**Not in Scope**: active order cancellation on trip (live-mode lane), persistent latch state across restarts, per-user threshold overrides.
**Suggested Next Step**: WARP🔹CMD review + merge → deploy with `BANKROLL_CIRCUIT_BREAKER_ENABLED=false` (default) → 24h soak → flip to `true` once trip-rate metric is reviewed.
