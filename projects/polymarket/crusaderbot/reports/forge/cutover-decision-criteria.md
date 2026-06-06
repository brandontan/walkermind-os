# WARP-78 Cutover Track C — orchestrator "beats router" decision criteria (PROPOSAL)

- Role: WARP•R00T
- Validation Tier: MINOR (decision-criteria proposal document; no code, no
  runtime change). Awaiting WARP🔹CMD sign-off — NOT self-merged as locked.
- Claim Level: FOUNDATION (defines the pass/fail rule; does not evaluate it).
- Validation Target: a quantified, pre-registered definition of "the EV
  comparator (orchestrator) beats the precedence router," locked BEFORE real
  `paper_real` data is seen, so the cutover call is objective not post-hoc.
- Not in Scope: running the criteria on real data (the real-data re-run);
  flipping any flag; the cutover code wire.
- Branch: `WARP/cutover-decision-criteria`
- **STATUS: PROPOSAL — WARP🔹CMD reviews + picks the margin threshold + signs
  off BEFORE the Track A real-data re-run. Per WARP-79 stop-condition, the
  criteria are not "locked" until CMD approves.**

---

## 1. What was built (the decision rule)

A pre-registered rule that turns the Track A holdout output (`evaluate_ev_holdout`
+ the paired 95% CI from `cutover_pipeline_dryrun.py`) into one of three verdicts
— **PASS / FAIL / RETRY** — for the `candle_auto + rule="auto"` orchestrator
cutover. Pre-registration is the whole point: the threshold is chosen here,
blind to the real numbers, so a marginal real result cannot be rationalized into
a PASS after the fact.

### 1.1 Primary metric

**EV/trade delta** `Δ = mean(comp_ev − router_ev)` over held-out settled
`paper_real` rows where BOTH the router pick and the comparator pick are
decidable (non-abstain, non-undecidable). Units are per-share realized EV
(`is_win − entry_price`), i.e. probability/price units in `[-1, +1]`. This is
exactly `ev_ab_compare(...).overall.ev_delta`, cross-checked against the
independent paired-Δ mean (the Track A `holdout_vs_paired_delta_consistent`
check). Per-rule horizon labels (`row_outcome_for_rule`) are used so `safe_close`
is judged at its real close−30s horizon.

### 1.2 Minimum margin threshold — 3 OPTIONS (CMD picks ONE)

Transaction friction sets the floor: the synthetic + live spread runs ≈0.012,
so a realized half-spread cost ≈0.006/trade. A credible edge must clear that
plus a buffer for estimation noise.

| Option | Margin `Δ ≥` | Rationale | Posture |
|---|---|---|---|
| **C1 — strict** | **+0.030** | ≈2.5× full spread; only cut over on a large, unambiguous edge. Lowest false-positive risk; may wait longer / never trip on a thin-but-real edge. | conservative |
| **C2 — moderate (RECOMMENDED)** | **+0.015** | ≈1.25× spread / ≈2.5× half-spread + buffer. Clears realistic friction with margin while still actionable. Balances false-cutover vs opportunity cost. | balanced |
| **C3 — lenient** | **+0.008** | Just above the half-spread cost. Trips on any net-of-friction positive edge; higher false-positive risk on a noisy sample — only safe if the CI gate (§1.3) is also strict. | aggressive |

> WARP•R00T recommends **C2 (+0.015)** paired with the §1.3 CI gate. Single
> number, not a range — CMD picks C1/C2/C3 (or overrides) before sign-off.

### 1.3 Statistical confidence requirement

The **overall** paired 95% CI on `Δ` must **exclude 0** (lower bound > 0). CI =
`mean ± 1.96·SE`, `SE = sd(paired Δ)/√n` over decided holdout comparisons (the
`cutover_pipeline_dryrun.py` `holdout_ci_*` computation). Margin (§1.2) AND
CI-excludes-0 must BOTH hold — a large point estimate with a CI straddling 0 is
RETRY, not PASS.

### 1.4 Per-cell sanity gates ("no catastrophic cell")

The 4 target cells — `BTC/5m`, `BTC/15m`, `ETH/5m`, `ETH/15m` — are each checked.
A cell is **catastrophic** if EITHER:
- `ev_delta_cell ≤ −0.020` (orchestrator materially worse than router in that
  cell — more than ~1.5× half-spread of damage), OR
- `comp_avg_ev_cell ≤ −0.050` (orchestrator's absolute realized EV is a large
  per-trade loss in that cell, even if it "beats" an even-worse router).

**Any single catastrophic cell ⇒ FAIL**, regardless of the overall delta. The
orchestrator routes all four cells in production; a strong aggregate must not
mask one cell bleeding capital.

### 1.5 Sample-size minimums per cell

- ≥ **200** settled `paper_real` rows/cell (the WARP-78 accrual gate), AND
- ≥ **60** held-out test rows/cell (≈30% of 200 at `train_fraction=0.7`), AND
- ≥ **40** *decided* comparisons/cell after abstain/undecidable removal.

A cell below ANY minimum is **INCONCLUSIVE**. If any target cell is inconclusive,
the overall verdict cannot be PASS — it is **RETRY** (accrue more, re-run),
unless §1.4 already forces FAIL.

### 1.6 Tie-break / RETRY rule

If `Δ > 0` but (margin < threshold) OR (CI includes 0) OR (a cell is
inconclusive) → **RETRY**: orchestrator stays inactive, precedence router
remains in control, re-run at the next data milestone (e.g. +100 rows/cell). A
marginal-but-not-significant result NEVER cuts over. Only `Δ ≤ 0` or a
catastrophic cell is a hard **FAIL** (→ Phase 3 iterate, not just "wait").

### 1.7 Verdict decision table

| Verdict | Condition (all of) |
|---|---|
| **PASS** | overall `Δ ≥ margin` (C1/C2/C3) AND overall 95% CI excludes 0 AND all 4 cells meet §1.5 minimums AND no catastrophic cell (§1.4) |
| **FAIL** | overall `Δ ≤ 0` OR any catastrophic cell (§1.4) |
| **RETRY** | otherwise (positive but sub-threshold / CI straddles 0 / a cell inconclusive) |

PASS → triggers the Track B code-cutover PR sequence. FAIL → orchestrator stays
inactive, Phase 3 iterates. RETRY → wait for more data + re-run.

## 2. Current system architecture (how the rule consumes the pipeline)

```
real paper_real settled rows (≥200/cell)
        │  ev_comparator --from-db  (writes config/ev_comparator_model.json)
        ▼
evaluate_ev_holdout(rows, train_fraction=0.7)  ──► per-cell + overall ev_delta
        │                                            + paired 95% CI (Track A harness)
        ▼
   §1.7 verdict table  ──►  PASS / FAIL / RETRY  ──►  WARP🔹CMD decision
```

The criteria are computed by the existing pipeline + the Track A harness; this
lane adds NO code — only the thresholds and the verdict logic Track D will
render and the real-data re-run will apply.

## 3. Files created / modified (full repo-root paths)

- Created: `projects/polymarket/crusaderbot/reports/forge/cutover-decision-criteria.md`
- State sync: `state/PROJECT_STATE.md`, `state/CHANGELOG.md`

No code touched.

## 4. What is working

- Every threshold maps to a value the pipeline already emits (overall/per-cell
  `ev_delta`, `comp_avg_ev`, `n`, `abstain`, `undecidable`, paired CI) — the rule
  is mechanically evaluable the moment real data lands, no new instrumentation.
- Pre-registration: numbers chosen blind to real data → no post-hoc drift.

## 5. Known issues / open decisions for CMD

- **Margin threshold (§1.2) is CMD's pick** — C1/C2/C3. R00T recommends C2.
- Catastrophic thresholds (−0.020 cell delta / −0.050 cell abs EV) and the
  sample minimums (200/60/40) are proposals; CMD may tighten/loosen.
- 15m cells historically thinner than 5m — if 15m accrual lags, the most likely
  real outcome is RETRY-on-15m even when 5m PASSes. CMD may choose to cut over
  per-cell (5m first) — flagged as a possible refinement, NOT assumed here.

## 6. What is next

- WARP🔹CMD: review, pick the margin option, sign off (or amend). This gate
  precedes the Track A real-data re-run per WARP-79.
- Track D renders these fields into the operator report template.
- On real data ≥200/cell: run the pipeline → apply §1.7 → CMD cutover decision.

Suggested Next Step: WARP🔹CMD selects the §1.2 margin option and signs off, so
the criteria are locked before any real number is visible.
