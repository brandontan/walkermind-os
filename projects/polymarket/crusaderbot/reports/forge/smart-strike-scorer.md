# WARP•FORGE — SMART STRIKE Phase 2 Scoring Orchestrator

- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target: the scorer + trainer + A/B modules (`domain/strategy/scorer*.py`), the shadow-log wiring in `services/signal_scan/signal_scan_job.py`, and the two new config flags. Pure shadow telemetry path.
- Not in Scope: execution, risk gate, sizing, kill switch, Oracle producer, DB schema/migrations, cutover (`SCORER_ACTIVE` stays False). The scorer's selection is logged only — the precedence router still controls execution.
- Suggested Next Step: WARP🔹CMD review → apply the (already-merged) migration 081 dataset is accruing; greenlight a `scorer_trainer.py --from-db` run against the dataset (163 rows / 132 settled) to replace the untrained stub, then read `scorer_ab.py --holdout` before any cutover decision.

---

## 1. What was built

The data-derived upgrade to the precedence-only SMART STRIKE router (WARP-71),
delivered SHADOW-only per the WARP-72 Phase 2 directive:

- **`StrategyScorer`** (`domain/strategy/scorer.py`) — ranks the three candle
  rules (`close_sweep` / `safe_close` / `flip_hunter`) by a per-cell,
  factor-weighted linear score loaded from `config/scorer_weights.json`, then
  applies the **Oracle deny-gate as an ADDITIVE veto** (WARP-66 per-preset
  thresholds: 2.0% / 1.0% / 3.0% at 5m). A rule whose Oracle edge is below its
  threshold (and `status == 'computed'`) is denied **regardless of score** — score
  can never override a denial. Fully fail-soft: a missing/untrained/malformed
  model degrades to a neutral scorer that exactly reproduces the precedence
  ladder, so the shadow path can never raise into the scan loop.
- **`scorer_trainer.py`** (`domain/strategy/scorer_trainer.py`) — offline CLI that
  reads settled `open_to_close` `factor_vectors` rows and derives per-cell,
  per-rule weights for **BTC/5m + ETH/5m**, writing `config/scorer_weights.json`.
  **SOL/5m has zero data → skipped with an explicit log** (`scorer_trainer_cell_skipped reason=no_data`), never a fabricated weight. The DB path is opt-in (`--from-db`) so it can never silently read prod.
- **Shadow wiring** in `signal_scan_job._scan_late_entry_for_preset` — on every
  candle evaluation (both `candle_auto` and single-rule presets) the scorer runs
  in parallel and emits a structured **`scorer_shadow`** log carrying
  `scorer_selected_rule` next to `router_selected_rule`, the per-rule scores, the
  denied set, and `scorer_active=False`. **Zero change to the merge/execution
  path.**
- **`scorer_ab.py`** (`domain/strategy/scorer_ab.py`) — compares scorer vs router
  win-rate on settled rows (per cell + overall: win-rate delta, agreement,
  abstain, undecidable). `evaluate_holdout()` provides the honest out-of-sample
  read the cutover criterion calls for.
- **Config flags** — `SCORER_SHADOW_ENABLED` (default True) and `SCORER_ACTIVE`
  (default False — router controls execution; cutover is CMD-gated and the
  selection authority is deliberately NOT implemented).

### Why the `scorer_selected_rule` label is a structured log, not a DB column

The directive's target-state #3 ("log `scorer_selected_rule` into `factor_vectors`")
collides with the Stop Condition "Modifying DB schema or migrations". `factor_vectors`
(migration 081) has no `scorer_selected_rule` column. Per the Scope note
("shadow **log** only") and the Acceptance criterion ("Shadow wiring **logs**
`scorer_selected_rule`"), it is emitted via structlog. The A/B harness needs no
column: it **re-scores** stored factor rows directly (win is derivable offline from
`fav_side` + the rule's underdog flag vs `realized_outcome`). Persisting the label
to a new column is deferred pending a CMD-approved migration.

## 2. Current system architecture

```
candle evaluation (signal_scan_job._scan_late_entry_for_preset)
  ├─ precedence router  ── picks rule by close_sweep > safe_close > flip_hunter  ──► EXECUTION (unchanged)
  └─ scorer SHADOW  ── StrategyScorer.rank(cell, factors, firing_rules, oracle…)
                          ├─ per-cell factor-weighted score (config/scorer_weights.json)
                          └─ + ADDITIVE Oracle deny-gate (WARP-66 thresholds)
                       ── logs "scorer_shadow" {scorer_selected_rule, router_selected_rule, scores, denied}

offline:  factor_vectors (settled, open_to_close)
            ├─ scorer_trainer.build_weights ──► config/scorer_weights.json   (BTC/5m, ETH/5m; SOL skipped)
            └─ scorer_ab.compare / evaluate_holdout ──► win-rate delta report
```

- Selection authority: **router only** (`SCORER_ACTIVE=False`). The scorer is a
  decoupled observer, exactly like the Phase-1 factor-vector emit and the Oracle
  advisory.
- The 7 factors and the win/side derivation reuse the Phase-1 `FactorVector` /
  `domain/signal/factors.py` contract (UP→YES, DOWN→NO; favorites enter `fav_side`,
  flip_hunter enters the opposite).

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/domain/strategy/scorer.py`
- `projects/polymarket/crusaderbot/domain/strategy/scorer_trainer.py`
- `projects/polymarket/crusaderbot/domain/strategy/scorer_ab.py`
- `projects/polymarket/crusaderbot/config/scorer_weights.json` (untrained stub)
- `projects/polymarket/crusaderbot/tests/test_warp72_scorer.py`

Modified:
- `projects/polymarket/crusaderbot/config.py` (+ `SCORER_SHADOW_ENABLED`, `SCORER_ACTIVE`)
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` (`_scorer_shadow_observe`, `_maybe_emit_scorer_shadow`, shadow calls in `_scan_late_entry_for_preset`)

State:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- 18 new hermetic tests pass (`test_warp72_scorer.py`): side/win helpers, neutral =
  precedence, missing-file fail-soft, Oracle deny-gate (additive + cannot be
  overridden by score), trainer derivation (correct weight signs, base win-rate,
  SOL skip), file round-trip, CLI refusal without a data source, DB fetch
  fail-soft, A/B compare/abstain/undecidable/holdout, and the shadow wiring
  (router pick = first firing rule; `scorer_shadow` log carries
  `scorer_selected_rule`; respects the disabled flag).
- Regression: `test_signal_scan_job.py`, `test_warp72_factor_dataset.py`,
  `test_config_defaults.py` all green. Full collectible suite: **2453 passed**
  (+3 vs baseline 2450), zero new failures. The 35 remaining failures + 20
  collection errors are **pre-existing environmental** (missing `fastapi` / `web3`
  / partial deps — confirmed identical on the stashed baseline).
- `ruff check` clean on all created/modified files.

## 5. Known issues

- **Weights file is an untrained stub.** Until a CMD-approved
  `scorer_trainer.py --from-db` run regenerates it, the scorer scores every rule
  0.0 and the precedence ladder decides — shadow output matches the router exactly.
- **A/B not yet run on real data.** `scorer_ab.py` is built + unit-tested but the
  scorer-vs-router proof on the live 132-settled dataset is pending the training
  run (Stop Condition: no prod DB access without CMD approval).
- **`scorer_selected_rule` is log-only** (see §1) — not queryable in
  `factor_vectors` without a future migration.
- **A/B candidate-menu approximation:** on a settled row the live router's matched
  rule subset is unrecoverable, so the A/B scores the full 3-rule menu. Documented
  in `scorer_ab.compare`.
- SOL/5m remains unscored by design (no data) — deferred.

## 6. What is next

1. WARP🔹CMD review (STANDARD). If deeper validation is wanted, reclassify to MAJOR
   for WARP•SENTINEL (STANDARD tasks do not run SENTINEL).
2. CMD-greenlit `scorer_trainer.py --from-db` against the accrued dataset →
   replace the stub → commit real weights.
3. Run `scorer_ab.py --from-db --holdout`; read the per-cell win-rate delta.
4. **Cutover (NOT in this lane):** flip `SCORER_ACTIVE=True` ONLY if the scorer
   beats the router on held-out settled data with ≥20 rows/cell — explicit CMD
   greenlight required; the selection-authority wiring is intentionally unbuilt.

---

Validation Tier: STANDARD → WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/smart-strike-scorer.md
