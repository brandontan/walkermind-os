# WARP-81 Phase 2 — late_entry_v3 OOS drift evaluator

Role: WARP•R00T (strategy validation tooling — validation-only, no runtime change)
Validation Tier: **MAJOR** (validation-correctness-critical: this proof gates a
judgement about the strategy producing ~95% of the book)
Claim Level: **FOUNDATION** (the evaluator + its math are built and unit-tested;
the proof itself runs in Phase 4 once `factor_vectors` paper_real rows accrue)
Validation Target: a chronological in-sample vs OOS realized-EV/trade comparison
of `late_entry_v3` per (asset, timeframe) cell, with drift + 95% CI + verdict.
Not in Scope: any `late_entry_v3` selection-logic change (validation only); any
touch on ev_comparator / scorer_trainer / orchestrator / scorer (WARP-79);
threshold changes; the Phase-4 run on real data (data-gated).
Suggested Next Step: WARP•SENTINEL or WARP🔹CMD review (MAJOR). Phase 3 = ~24h
snapshot/row accrual; Phase 4 = run `--from-db` and deliver
`reports/forge/late-entry-v3-oos-proof.md`.

---

## 1. What was built

`domain/research/late_entry_oos_evaluator.py` — a self-contained, stdlib-only OOS
drift evaluator. Per (asset, timeframe) cell it:

1. Orders the cell's **settled** `factor_vectors` rows chronologically (candle
   close epoch, then settled_at).
2. Splits 70/30 → in-sample (older) / OOS (newer).
3. Computes mean realized per-trade EV on each split.
4. Reports `drift = OOS_ev − in_sample_ev` with a two-sample (Welch SE) 95% CI and
   a `significant` flag (CI excludes 0).
5. Emits a per-cell verdict: `holds` / `degrades` / `improves` / `inconclusive_thin`,
   plus a pooled `OVERALL` row and a markdown renderer for the Phase-4 report.

Realized per-trade EV uses the production convention exactly — `ev = (1 if the
recorded entry_side matched the realized winner else 0) − entry_price`, with
UP→YES / DOWN→NO and FLAT/unresolved skipped (never a fabricated loss), and the
`safe_close` rule scored on its open→(close−30s) horizon (`realized_outcome_safe_close`,
falling back to `realized_outcome`).

**Independent reimplementation, by design.** The convention is re-derived locally
rather than imported from `scorer.py` / `scorer_trainer.py` for two reasons: (a)
WARP-79 locks those paths out of this lane, and (b) an OOS *proof* must not depend
on the code it validates — an independent scorer cross-checks the production one.
It reads `entry_side` / `entry_price` exactly as `late_entry_v3` recorded them.

## 2. Current system architecture

No runtime/trading/selection change. This is a pure read-side research module
(like `late_entry_oos.py` and `report_cutover_holdout.py`): invoked on demand via
`python -m ...domain.research.late_entry_oos_evaluator --from-db`, never from the
scan loop. The DB path is gated behind `--from-db` and defaults to the
`paper_real` provenance (WARP-77 #1655 enum) so the proof is never run on the
paper_synthetic seed; the loader is fail-soft (→ `[]` on any DB error).

It complements the existing WARP-58 `late_entry_oos.py`: that harness measures
absolute `edge_bps` over the `market_snapshots` walk-forward substrate, whereas
this one answers the WARP-81 question — *does in-sample edge survive
out-of-sample?* — over the settled `factor_vectors` rows that already exist
(paper_real 77/75 per 5m cell and growing). `market_snapshots` is an optional
Phase-4 enrichment (final-window entry reconstruction), not required to build or
test the evaluator.

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/domain/research/late_entry_oos_evaluator.py` — the evaluator (pure math + gated DB loader + report renderer + CLI)
- `projects/polymarket/crusaderbot/tests/test_late_entry_oos_evaluator.py` — 15 hermetic tests
- `projects/polymarket/crusaderbot/reports/forge/late-entry-v3-oos-evaluator.md` — this report

Modified:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `projects/polymarket/crusaderbot/state/CHANGELOG.md` — synced

## 4. What is working

- 15/15 hermetic tests pass; `ruff` clean; `py_compile` clean.
- Realized-EV convention verified (favorite win/loss, NO-side win, FLAT/bad-side/
  missing-price → undecidable-skip).
- `safe_close` horizon override verified (uses `realized_outcome_safe_close`;
  close_sweep ignores it; router-selected rule drives the horizon).
- Two-sample CI math verified (zero-variance exact case + noisy straddle-zero case).
- Verdict logic verified end-to-end on synthetic cells: `degrades` (OOS collapse,
  CI excludes 0), `holds` (stable), `inconclusive_thin` (< MIN_PER_SPLIT=30/split).
- Chronological split verified by epoch (out-of-order input ordered correctly).
- Multi-cell separation + pooled `OVERALL` row + undecidable-row exclusion verified.
- Report renderer verified (table headers, significance marker, cell labels).

## 5. Known issues

- **The proof is not yet RUN** — this lane builds + tests the evaluator
  (FOUNDATION). Phase 4 runs `--from-db` once paper_real rows accrue ≥
  MIN_PER_SPLIT (30) per split per cell (~60+ settled/cell). Current paper_real is
  ~77/75 per 5m cell → BTC/5m & ETH/5m are near the threshold; 15m cells are
  terminal (venue dropped updown-15m, per WARP-78) and will read inconclusive.
- The split is on `factor_vectors` rows (per evaluated candle), the strategy's
  realized edge across decidable evaluations. A `selected_by_router`-only variant
  (actual entries) is a trivial filter follow-up if CMD wants the narrower
  population.
- z (normal) CI rather than a t-interval — negligible at n ≥ 30/split and avoids a
  scipy dependency.

## 6. What is next

1. WARP•SENTINEL / WARP🔹CMD review (MAJOR tier).
2. Phase 3: ~24h accrual of settled paper_real rows (independent of the
   SCAN_SNAPSHOT flip; snapshot enrichment is optional).
3. Phase 4: run the evaluator `--from-db` → deliver
   `reports/forge/late-entry-v3-oos-proof.md` with the per-cell drift verdict;
   if catastrophic drift → STOP + escalate (could reprioritize the WARP-79 cutover).

---

Validation Handoff (NEXT PRIORITY):

```
WARP•SENTINEL validation recommended for late_entry_v3 OOS evaluator before the
Phase-4 proof is trusted (MAJOR — validation-correctness-critical).
Source: projects/polymarket/crusaderbot/reports/forge/late-entry-v3-oos-evaluator.md
Tier: MAJOR
```
