# WARP-78 Cutover Track A — EV pipeline dry-run (synthetic)

- Role: WARP•R00T
- Validation Tier: MINOR (non-runtime research/validation harness + hermetic
  tests; touches NO prod code path, NO selection/sizing/gate/runtime, NO DB,
  writes nothing to `factor_vectors`). Merged under WARP•R00T authority.
- Claim Level: FOUNDATION (proves the offline model-generation + holdout
  pipeline mechanics on synthetic data with a known injected ground truth; this
  is NOT a real-runtime integration claim).
- Validation Target: `derive_ev_model` → `EVComparator` → `ev_ab_compare` /
  `evaluate_ev_holdout` are bug-free and recover an injected factor→EV signal,
  before real paper_real rows land.
- Not in Scope: flipping `ORCHESTRATOR_ACTIVE`; any prod behavior change; the
  real-data model generation (Track A re-run when paper_real ≥200/cell); the
  cutover routing wire itself (does not yet exist — see §5).
- Branch: `WARP/cutover-pipeline-dryrun`

---

## 1. What was built

A self-contained, in-memory dry-run harness that exercises the REAL Phase-3 EV
pipeline against synthetic-but-realistic `factor_vectors` rows carrying a KNOWN
injected ground truth, so the pipeline output is checkable against expectation
weeks before the real `paper_real` data hits ≥200/cell.

- **`scripts/cutover_pipeline_dryrun.py`** — generator + validator + CLI:
  - `generate_synthetic_rows(rows_per_cell, seed)` — 200 rows × 4 cells
    (btc/5m, btc/15m, eth/5m, eth/15m) with realistic distributions for the 7
    model factors plus the full broader schema shape (momentum_delta,
    realized_vol, ask_diff, complete_set_edge, entry_side/price, safe_close
    labels, provenance, …). **In-memory only** — no DB, no Supabase, no write
    to `factor_vectors`.
  - **Injected ground truth:** `momentum` (and weaker `oracle_edge`) tilt the
    favorite's win probability; favorite rules (close_sweep / safe_close) gain
    +EV with momentum, the underdog rule (flip_hunter) is the mirror image
    (+EV when momentum is negative). `volatility_sigma` is a per-asset constant
    (dead signal). The router pick is ttl-window-driven and momentum-blind, so
    a momentum-aware comparator should beat it out-of-sample.
  - Runs `derive_ev_model` → `ev_ab_compare` (in-sample) and
    `evaluate_ev_holdout` (out-of-sample), computes a 95% confidence interval on
    the paired per-row EV delta, and prints a PASS/FAIL correctness report.
- **`tests/test_cutover_pipeline_dryrun.py`** — 4 hermetic tests: all checks
  pass at the canonical seed; pipeline correctness is stable across seeds
  (1/7/99); momentum sign + dead-factor recovery is asserted directly.

## 2. Current system architecture

The EV pipeline is unchanged by this lane. The harness is a pure consumer of the
existing public surface in `domain/strategy/ev_comparator.py` +
`domain/strategy/scorer.py`:

```
synthetic rows (in-memory, injected EV signal)
        │
        ▼
derive_ev_model(rows)  ──► schema-v2 model {cells:{norm, rules:{base_ev, weights}}}
        │                         │
        │                         ▼  write_ev_model → JSON → EVComparator.from_file
        ▼
EVComparator.from_model
        │
        ├─► ev_ab_compare(rows, comparator)        (in-sample router-vs-comparator)
        └─► evaluate_ev_holdout(rows)              (70/30 per-cell split, OOS)
                    │
                    ▼  paired per-row Δ(comp − router) → mean ± 1.96·SE (95% CI)
```

## 3. Files created / modified (full repo-root paths)

- Created: `projects/polymarket/crusaderbot/scripts/cutover_pipeline_dryrun.py`
- Created: `projects/polymarket/crusaderbot/tests/test_cutover_pipeline_dryrun.py`
- Created: `projects/polymarket/crusaderbot/reports/forge/cutover-pipeline-dryrun.md`
- State sync: `state/PROJECT_STATE.md`, `state/CHANGELOG.md`

No production module was modified.

## 4. What is working

Pipeline-correctness checklist — all hard (correctness) checks PASS at seed=78,
800 rows (`python scripts/cutover_pipeline_dryrun.py`):

| Check | Result |
|---|---|
| no NaN / non-finite anywhere in the model | PASS |
| momentum weight positive for favorite rules (8/8) | PASS |
| momentum weight negative for flip_hunter (4/4) | PASS |
| dead `volatility_sigma` weight floored to exactly 0.0 (4/4) | PASS |
| momentum dominates non-injected noise factors (4/4) | PASS |
| JSON serialize → reload → identical comparator picks (0 mismatches) | PASS |
| holdout overall ev_delta positive (+0.110) | PASS |
| holdout per-cell avgs finite | PASS |
| holdout 95% CI computed (n=240, [+0.032, +0.189]) | PASS |
| `ev_ab_compare` overall ev_delta == independent paired-Δ mean (anti column-map bug) | PASS |
| holdout CI excludes zero (INFORMATIONAL — statistical power) | INFO |

Recovered model matches the injected design: `momentum` is the dominant weight
per cell (≈ +0.23..+0.31 for close_sweep, mirror-negative for flip_hunter),
`oracle_edge` is the consistent second driver, `volatility_sigma` contributes 0.

- `pytest tests/test_cutover_pipeline_dryrun.py` → 4 passed. `ruff` clean.

## 5. Known issues

- **The cutover routing wire does not exist yet (expected).** `ORCHESTRATOR_ACTIVE`
  is consulted in exactly ONE place — `late_entry_v3.py:330`, the shadow logger,
  which merely returns early when True. Flipping it today silences shadow logging
  and changes NO routing: `candle_auto` still uses the precedence router. The
  comparator-routes-selection wire is genuinely unbuilt and deferred to the
  cutover lane (documented in the Phase-3 state + AdminUserDrawer.tsx comment).
  Track B's runbook documents this accurately.
- **No `config/ev_comparator_model.json` exists.** `get_ev_comparator()` →
  `neutral()` → abstains on every candle. The runtime model is generated only
  from settled `paper_real` rows (the data-gated ≥200/cell milestone). Activating
  comparator routing before that file exists would make `candle_auto` abstain
  into zero trades — a live-user hazard the data-gate protects against.
- `ci_excludes_zero` is effect-size / sample dependent (varies by seed). It is
  reported informationally here; on REAL data it is the actual cutover decision
  criterion (Track C), not a dry-run correctness gate.

## 6. What is next

- **Track C** locks the quantified "beats router" criteria (margin threshold,
  CI requirement, per-cell safety gate) BEFORE real data is seen.
- **Track D** turns this harness's holdout output into the operator report
  template.
- **Track B** documents the cutover runbook against the real (code-level)
  ORCHESTRATOR_ACTIVE mechanism.
- **Real-data re-run:** when paper_real ≥200/cell, run `ev_comparator --from-db`
  to write the real model, then `evaluate_ev_holdout` on real rows → Track C
  evaluation → WARP🔹CMD cutover decision.

Suggested Next Step: WARP🔹CMD review + merge (MINOR, non-runtime). Then proceed
to Track C (decision criteria) for CMD sign-off.
