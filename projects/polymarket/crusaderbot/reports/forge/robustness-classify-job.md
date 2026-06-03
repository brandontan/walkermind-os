# WARP•FORGE — robustness-classify-job (WARP-53 Phase-2c-1b, part 1)

Role: WARP•FORGE (under the WARP•R00T PLAYBOOK epic, WARP-53)
Validation Tier: **STANDARD** (scheduler job; pure read-side analytics, no trading effect)
Claim Level: **NARROW INTEGRATION** (one gated scheduler job, default OFF)
Validation Target: the scheduled `classify_modules` refresh job + its gated registration.
Not in Scope: wiring `live_eligible` into the live execution mode-decision (the
capital-path part of 2c-1b — see below, deliberately deferred); 2c-3 replay engine.
Suggested Next Step: WARP🔹CMD review/merge; operator sets the flag; then the
execution-path gate-wire as its own MAJOR, separately-reviewed lane.

---

## 1. What was built

Phase-2c-1b (part 1) — makes the Phase-2c-1 robustness analytics actually **run** in the
runtime. Until now `classify_modules` existed but nothing called it, so `module_robustness`
was never populated. This adds a scheduled refresh:

- **`domain/research/robustness.py`** — `run_job()`: recomputes + persists robustness
  verdicts for the three standard risk profiles (conservative / balanced / aggressive)
  from paper trade history. Fail-soft per profile (one profile's failure never aborts the
  rest; `classify_modules` already swallows its own DB errors). Exposes `ROBUSTNESS_JOB_ID`.
- **`scheduler.py`** — registers `run_job` on an interval **only when**
  `ROBUSTNESS_CLASSIFY_ENABLED` is on (mirrors the Heisenberg/fast-track gated-job pattern),
  `max_instances=1`, coalesce.
- **`config.py`** — `ROBUSTNESS_CLASSIFY_ENABLED = False` (default OFF) +
  `ROBUSTNESS_CLASSIFY_INTERVAL_SEC = 3600` (hourly).

## 2. Why the execution gate-wire is deferred (not in this lane)

The other half of 2c-1b — having `live_eligible` force an UNTRADEABLE module from live →
paper — touches the **money path**: the per-candidate mode decision lives inside
`_engine.execute(signal)`. Even as a downgrade-only, default-OFF change it is a
capital-path edit that warrants its own deliberate, MAJOR-tier, separately-reviewed lane
(per the repo's execution-safety posture) rather than riding in with an analytics job.
This lane deliberately stops at making the classification **run + be observable**; the
gate-wire is the clean next step. The `live_eligible` API (merged in #1578) is unchanged
and ready for it.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/domain/research/robustness.py` — `run_job` + `ROBUSTNESS_JOB_ID`
- `projects/polymarket/crusaderbot/scheduler.py` — gated job registration
- `projects/polymarket/crusaderbot/config.py` — `ROBUSTNESS_CLASSIFY_ENABLED` + interval
- `projects/polymarket/crusaderbot/tests/test_research_robustness.py` — +2 run_job tests
- `projects/polymarket/crusaderbot/reports/forge/robustness-classify-job.md` — this report
- State: `state/PROJECT_STATE.md` · `state/WORKTODO.md` · `state/CHANGELOG.md`

## 4. What is working

- **23 tests pass** (21 existing + 2 new: run_job classifies each standard profile in
  paper mode; one profile raising does not abort the others). ruff + py_compile clean.
- When `ROBUSTNESS_CLASSIFY_ENABLED` is off (default), the scheduler registers nothing —
  zero runtime change. When on, the job populates `module_robustness` hourly, fail-soft.

## 5. Known issues

- Requires migration 079 applied (else `classify_modules` fail-soft reads/writes nothing).
- Verdicts are only meaningful once a module has ≥30 closed paper positions; until then
  every module is INSUFFICIENT_DATA.
- The classification is computed but not yet consulted by any live decision (by design —
  the gate-wire is the deferred follow-up).

## 6. What is next

- 2c-1b part 2 (MAJOR): wire `live_eligible` into the execution mode-decision (downgrade
  UNTRADEABLE → paper) behind `ROBUSTNESS_GATE_ENABLED`, default OFF, classifications cached
  once per scan (no per-candidate DB read). Separately reviewed.
- 2c-3: walk-forward replay engine over `market_snapshots` once data accrues.

---

- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION (one gated scheduler job, default OFF)
- Validation Target: scheduled classify_modules refresh + gated registration
- Not in Scope: execution gate-wire (deferred MAJOR lane), replay engine
- Suggested Next Step: WARP🔹CMD review/merge → operator enables flag → gate-wire lane
