# WARP•R00T — risk-limit-reconciliation

**Branch:** `WARP/ROOT/risk-limit-reconciliation`
**Role:** WARP•R00T (system hardening)
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** the risk-gate path's daily-loss + correlated-exposure evaluation. Closes the C-5/C-6 dual-evaluation drift surfaced by the pre-public audit so the per-profile limits displayed to LIVE users (Conservative −$200 / Balanced −$500 / Aggressive −$1000; 40% correlated-exposure cap) are the actual enforced limits unless the operator explicitly tightens them via env.
**Not in Scope:** the C-3 concurrency-cap policy (`MAX_CONCURRENT_TRADES=5` dead vs per-profile 5/12/20), the C-4 `_process_candidate` decomposition, the LIVE live-fire validation, and any change to the Track-D per-user single-position cap (`MAX_SINGLE_POSITION_PCT`) or open-position count cap (`MAX_OPEN_POSITIONS`).

---

## 1. What was built

Two duplicate cap evaluations in the risk gate were removed and re-routed through reconciled "most-restrictive wins" helpers:

- **C-5 — daily-loss cap.** Previously `validate_risk_caps` step 0 cap 3 rejected on `settings.MAX_DAILY_LOSS_USD = -$50` (system-wide) and gate step 5 rejected on `effective_daily_loss(profile)` ∈ {−$200, −$500, −$1000}. Step 0 *always* fired first, so the profile cap shown in the UI was effectively dead. `effective_daily_loss()` now accepts a `system_floor=` kwarg; gate step 5 passes `settings.MAX_DAILY_LOSS_USD` into it; `validate_risk_caps` no longer enforces a daily-loss cap of its own. Most-restrictive semantics preserved: with the default `MAX_DAILY_LOSS_USD=-50`, behaviour at step 5 matches the old step 0 cap 3 exactly; with the operator-tunable env relaxed to e.g. `-2000`, the profile cap becomes the live enforced limit.

- **C-6 — correlated-exposure cap.** Previously `validate_risk_caps` step 0 cap 2 rejected on `settings.MAX_TOTAL_EXPOSURE_PCT = 0.60` and gate step 8 rejected on `MAX_CORRELATED_EXPOSURE = 0.40`. Step 0 fired first and was always looser, so it was dead code; step 8's 0.40 always governed. New `effective_exposure_cap(system_cap=)` helper returns `min()` of the two; gate step 8 consumes it; `validate_risk_caps` no longer enforces a total-exposure cap of its own. With `MAX_TOTAL_EXPOSURE_PCT=0.60` (the current default), behaviour is unchanged. The operator can now tighten via env (e.g. `0.20`) and have it actually fire.

What didn't change: per-user `MAX_SINGLE_POSITION_PCT` (Cap 1) and `MAX_OPEN_POSITIONS` (Cap 4) remain in `validate_risk_caps` — they are not duplicated elsewhere. The system hard stop `DAILY_LOSS_HARD_STOP=-2000` and the per-profile caps are untouched. `assert_live_guards`, paper/live engines, kill switch, and slippage / market-impact gates are untouched.

## 2. Current system architecture

```
RISK gate (evaluate)
  0  validate_risk_caps          → balance / single-pos / open-count (Caps 0/1/4)
  ...
  5  daily_loss                  → effective_daily_loss(profile, user_override,
                                                        system_floor=MAX_DAILY_LOSS_USD)
  ...
  8  correlated_exposure         → effective_exposure_cap(system_cap=MAX_TOTAL_EXPOSURE_PCT)
  ...
```

Helpers live in `domain/risk/constants.py` so callers (gate, future readiness validators, UI computations) share a single most-restrictive formula. `resume_safety_check` (Lane 1 — separate PR) will also benefit once both lanes merge; no change to that helper is needed in this lane because the consolidation lives behind the same step 5 / step 8 numbers.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/domain/risk/constants.py` — extend `effective_daily_loss(..., system_floor=None)`; add `effective_exposure_cap(system_cap=None)`.
- `projects/polymarket/crusaderbot/domain/risk/gate.py` — `validate_risk_caps` drops caps 2 + 3; `evaluate` step 5 passes `system_floor=settings.MAX_DAILY_LOSS_USD`; `evaluate` step 8 uses `effective_exposure_cap(system_cap=settings.MAX_TOTAL_EXPOSURE_PCT)`.

Created:
- `projects/polymarket/crusaderbot/tests/test_risk_limit_reconciliation.py` — 18 hermetic tests.
- `projects/polymarket/crusaderbot/reports/forge/risk-limit-reconciliation.md` — this report.

## 4. What is working

- `pytest tests/test_risk_limit_reconciliation.py` — 18/18 pass (unit coverage on both helpers + integration coverage on `validate_risk_caps` Cap 1 / Cap 4 / balance, plus gate step 5 + step 8 enforcing the reconciled cap with both default and operator-tightened env values).
- Full project suite: **2212 passed**. Only sandbox-environment failures remain (4× `poly_eip712_structs` SDK missing in this runner) — same baseline as Lane 1; **zero regression** introduced by this lane.
- `pytest tests/test_late_entry_v3.py::test_effective_daily_loss_*` and the existing `test_fallback.py` Track-D settings stubs continue to pass — the helper extension is signature-compatible (`system_floor` defaults to `None`, behaviour identical when omitted).
- `py_compile` + `ruff check` clean on the changed modules.

## 5. Known issues

- Default-behaviour preservation is intentional: with `MAX_DAILY_LOSS_USD=-50` and `MAX_TOTAL_EXPOSURE_PCT=0.60` (fly.toml / config defaults), gate step 5 still rejects at −$50 and step 8 still rejects at 0.40. To realise the truth-in-UI win at LIVE the operator must relax those env values (e.g. `MAX_DAILY_LOSS_USD=-2000` so the per-profile cap fires, `MAX_TOTAL_EXPOSURE_PCT=1.0` so `MAX_CORRELATED_EXPOSURE` alone governs). That env flip is an explicit operator step before LIVE and is captured in the next-steps section below.
- This lane branches from clean `main`. Lane 1 (`WARP/ROOT/risk-path-hardening`) adds `resume_safety_check`; both lanes touch separate functions in `domain/risk/gate.py` and `domain/risk/constants.py` (Lane 1 adds the `"weather"` STRATEGY_AVAILABILITY entry). Merge order does not matter; the second to merge needs a trivial rebase only.

## 6. What is next

- **WARP🔹CMD review** of `WARP/ROOT/risk-limit-reconciliation` (tier STANDARD → no SENTINEL required by CLAUDE.md, but boss may opt-in).
- Before LIVE flip: operator decides whether to relax `MAX_DAILY_LOSS_USD` and `MAX_TOTAL_EXPOSURE_PCT` so per-profile limits become the visible truth at LIVE. Default = keep tight (current behaviour = unchanged).
- Follow-up lane **C-3** concurrency policy — WARP🔹CMD decides whether to enforce global 5 or ratify per-profile 5/12/20 and retire the dead `MAX_CONCURRENT_TRADES` constant; `audit_risk_constants` extended at the same time.
- Follow-up lane **C-4** decompose `_process_candidate` (~600 lines) into composable pipeline-step gates.
- Follow-up lane **LIVE live-fire validation** — `USE_REAL_CLOB=True` end-to-end on a small cap.

---

**Suggested Next Step:** WARP🔹CMD review of `WARP/ROOT/risk-limit-reconciliation` (STANDARD, NARROW INTEGRATION). Behaviour preserved at defaults; the win lands the moment LIVE-bound env values are relaxed to surface the per-profile limits.
