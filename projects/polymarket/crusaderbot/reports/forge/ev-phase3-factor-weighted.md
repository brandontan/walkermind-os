# WARP-78 Phase 3 — Factor-Weighted EV Estimation (Shadow)

## 1. What was built

Phase 3 upgrades the EV-comparator from base-rate mean EV (Phase 2, schema v1) to a
**factor-weighted linear EV model** (schema v2) conditioned on the 7-factor surface:

```
estimated_ev = base_ev + Σ weight[f] × z_f
```

- `base_ev`: shrunk mean realized EV for (cell, rule), using per-rule horizon labels
  (safe_close → `realized_outcome_safe_close`; others → `realized_outcome`)
- `weight[f]`: Pearson correlation of factor f with the per-rule EV label, shrunk by
  `pearson × n/(n+K)` (default K=10) to prevent thin-data rules from dominating
- `z_f`: live factor value standardized as `(value - mean) / std` using per-cell
  normalization stats stored in the model

**Live shadow wiring**: `late_entry_v3._ev_comparator_shadow()` now extracts the full
factor surface from the FactorVector and passes it to the comparator's `select()`,
enabling factor-conditioned rule selection in shadow mode.

**Holdout A/B infrastructure**: `evaluate_ev_holdout()` splits settled rows 70/30 by
cell, trains on the training set, evaluates comparator vs router on the held-out set.
`ev_ab_compare()` runs a comparator against any set of settled rows and returns
per-cell + overall agreement and EV delta statistics.

### Factor-EV Correlations (1236 settled rows, Supabase)

**BTC/5m** (n: cs=40, fh=340, sc=26):
| Factor       | close_sweep | flip_hunter | safe_close |
|-------------|-------------|-------------|------------|
| momentum    | +0.73       | +0.56       | +0.91      |
| spread      | −0.33       | +0.06       | −0.11      |
| oracle_edge | −0.14       | +0.03       | −0.04      |
| liquidity   | −0.06       | −0.07       | −0.08      |

**ETH/5m** (n: cs=46, fh=305, sc=33):
| Factor       | close_sweep | flip_hunter | safe_close |
|-------------|-------------|-------------|------------|
| momentum    | +0.66       | +0.52       | +0.88      |
| spread      | +0.09       | +0.06       | −0.10      |
| oracle_edge | −0.24       | +0.06       | −0.23      |
| liquidity   | +0.12       | −0.12       | +0.28      |

**Dominant factor**: momentum (r=0.52–0.91 across all rules and cells).
Oracle_edge and spread are secondary but meaningful for close_sweep/safe_close.

## 2. Current system architecture

```
factor_vectors (Supabase, 1236 settled rows)
    ↓ offline derive_ev_model()
ev_comparator_model.json (schema v2)
    ↓ EVComparator.from_file()
late_entry_v3._ev_comparator_shadow()
    ↓ factors={momentum, vol_sigma, liquidity, spread, ob_depth, ttl, oracle_edge}
comparator.select(cell_key, rules, factors=factors)
    ↓ estimated_ev = base_ev + Σ w[f]*z_f per rule
    ↓ argmax (abstain if all ≤ 0.0)
shadow log: ev_comparator_shadow {cell, router_rule, ev_pick, ev_estimates}
```

ORCHESTRATOR_ACTIVE = False (shadow mode). SCORER_ACTIVE = False.
Router controls all selection. No execution/gate/sizing change.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/domain/strategy/ev_comparator.py` — schema v2
  rewrite: `derive_ev_model()` computes per-cell norm + per-rule factor weights;
  `EVComparator.estimate_ev()` accepts `factors` kwarg for conditioned estimate;
  `rank()`/`select()` pass factors through; `_z()` standardizes factors; `_pearson()`
  and `_pop_std()` stats helpers; `ev_ab_compare()` and `evaluate_ev_holdout()` added;
  `format_ev_model_summary()` updated for v2 shape; v1 compat preserved (reads
  `shrunk_ev` from flat cell keys). 579 lines.
- `projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py` —
  `_ev_comparator_shadow()` extracts factor surface from FactorVector using `FACTORS`
  list and passes it to `comparator.select()`.
- `projects/polymarket/crusaderbot/tests/test_warp78_ev_comparator.py` — 16 hermetic
  tests for Phase 3: model shape, factor weights (nonzero for varying, zero for
  constant), shrinkage, sc horizon labels, factor-conditioned selection, ranking flip,
  abstain, v1 compat, neutral, ORCHESTRATOR_ACTIVE=False, schema version, write/load
  round-trip, ev_ab_compare, evaluate_ev_holdout.

## 4. What is working

- `derive_ev_model()` produces v2 model with per-cell normalization stats and per-rule
  factor weights (shrunk Pearson correlations)
- Factor-conditioned EV estimation: `estimate_ev(cell, rule, factors=...)` adjusts
  base_ev by the weighted z-scores of live factors
- Factor adjustment flips rankings: tested with oracle_edge z=3.5 causing close_sweep
  to lose to flip_hunter despite higher base_ev
- Abstain logic: comparator picks nothing when all rules have negative estimated EV
- v1 model compatibility preserved (reads `shrunk_ev` from flat cell keys)
- Holdout A/B infrastructure: `evaluate_ev_holdout()` trains on 70% of rows, evaluates
  on 30%, returns per-cell + overall statistics
- Shadow wiring: factor surface flows from FactorVector → comparator in late_entry_v3
- All 24 tests pass (16 ev_comparator + 8 sc_label_routing)

## 5. Known issues

- Model file `config/ev_comparator_model.json` not yet generated from production data
  (comparator uses neutral fallback until model exists on disk)
- safe_close horizon labels (`realized_outcome_safe_close`) available for only 92 of
  1236 settled rows — sc-corrected safe_close EV model will be thin-data until more
  paper_real rows accrue with the close-30s tick present
- 15m cells (BTC/15m, ETH/15m, SOL/15m) have very few router-assigned rows — model
  accuracy limited until more data accrues
- ORCHESTRATOR_ACTIVE and SCORER_ACTIVE remain False — no selection change in production

## 6. What is next

- Generate the v2 model file from production Supabase data via
  `ev_comparator.py --from-db` (CLI already wired)
- Continue accruing paper_real settled rows with safe_close horizon labels
- At ~200+ paper_real rows per key cell: re-derive model → run holdout A/B →
  WARP🔹CMD cutover decision (ORCHESTRATOR_ACTIVE flip)
- Monitor momentum dominance in factor weights — if it persists, may simplify to a
  momentum-only conditioner

---

**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** factor-weighted EV estimation model (schema v2) + shadow wiring + holdout A/B infrastructure
**Not in Scope:** ORCHESTRATOR_ACTIVE flip, SCORER_ACTIVE flip, model file generation from production data, factor surface changes
**Suggested Next Step:** WARP🔹CMD review. Generate v2 model from Supabase data when paper_real rows reach ~200/cell.
