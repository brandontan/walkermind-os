# WARP-86 Phase 0a — TP/SL EV Grid-Sweep

Validation Tier: STANDARD (analysis only — no runtime/flag change)
Claim Level: FOUNDATION
Validation Target: a reproducible 475-combo TP/SL EV grid-sweep over the settled
trade history with bootstrap 95% CIs + a Phase-0b recommendation. SCORER_ACTIVE /
ORCHESTRATOR_ACTIVE / ENABLE_LIVE_TRADING untouched.
Not in Scope: any strategy/risk/execution/domain code; migrations; flipping any
flag; live TP/SL change.
Suggested Next Step: WARP🔹CMD review of the recommendation (keep 1.5/0.5; open a
per-position MFE/MAE excursion-capture lane before any TP/SL cutover).

---

## 1. What was built

`analysis/warp86_ev_gridsweep.py` — a pure, idempotent, typed read-only analysis
script that runs a 475-combo (25 TP × 19 SL) grid-sweep on settled trade history,
with a 1000× bootstrap 95% CI per combo, and emits a CSV (all combos) + a
human-readable MD report. Two data paths: `--from-db` (exact per-row via
`DATABASE_URL`/asyncpg) and a default offline `--snapshot` (committed read-only
binned histogram) so the committed artifacts are reproducible without DB creds.

### Data-source correction (directive premise was off)
The directive named `positions.realized_outcome` with `paper=true`. The live
`positions` table has **no `realized_outcome` column** and was wiped to ~48 rows
for the clean-test start. The settled outcome history with the n≥1445 baseline
lives in **`factor_vectors`** (settled = `realized_outcome IS NOT NULL`), carrying
`entry_side`/`entry_price`/`realized_outcome`/`asset`/`timeframe`/`data_source`.
The sweep runs there. Win convention (repo standard): YES entry wins on
`realized_outcome='UP'`, NO entry wins on `DOWN`.

### Result (headline — this is the finding, not a fitted optimum)
- ALL settled n=**1891** (≥1445 ✓), win-rate **0.68**; paper_real n=**764**,
  win-rate **0.70**. Winners are heavy favourites (entry price ~0.9+); losers are
  longshots (~0.03).
- **Baseline reconciliation:** E.1 realized-EV metric (`mean(is_win − entry_price)`)
  = **+0.53%** on paper_real — approximately reproduces the E.1 #1684 baseline
  (+0.48%, n=1445). ALL is ~0% (diluted by the slightly-negative paper_synthetic seed).
- **The grid sweep cannot identify a robust interior TP/SL.** Under the directive's
  literal convention (win→+TP, loss→−SL) AND a more-accurate entry-price-capped
  convention (win→`min(TP,(1−p)/p)`, loss→−SL), EV is strictly **monotone-decreasing
  in SL** → the "optimum" is always the minimum-SL / maximum-TP corner
  (TP 2.90 / SL 0.10). That is an **artifact of the missing intra-trade price path**
  (no per-position MFE/MAE): the model never sees a winner a tight stop would have
  cut, so it systematically under-prices the stop (PROJECT_STATE KNOWN ISSUES:
  looser-SL bundles are BOUNDED, not point-estimable).
- The capped convention also shows **TP is largely inert**: favourite winners'
  settlement ceiling `(1−p)/p` is small, so a large TP is unreachable (1.5/0.5 is
  +0.86 under convention A but −0.07 under the capped convention) — the conventions
  diverge precisely because none models actual position-level P&L with a path.

## 2. Current system architecture

No runtime change. New analysis-only module under `analysis/`. Reads `factor_vectors`
(read-only). Outputs to `analysis/reports/`. Composes conceptually with WARP-78 EV
cutover work but writes nothing into it.

## 3. Files created / modified

- Created: `projects/polymarket/crusaderbot/analysis/warp86_ev_gridsweep.py`
- Created: `projects/polymarket/crusaderbot/analysis/data/warp86_settled_histogram.csv` (read-only binned snapshot)
- Created: `projects/polymarket/crusaderbot/analysis/reports/warp86_ev_gridsweep_20260608.csv` (950 rows: 475 combos × {ALL, paper_real})
- Created: `projects/polymarket/crusaderbot/analysis/reports/warp86_ev_gridsweep_20260608.md`
- Modified: `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- Modified: `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- Script runs end-to-end (`475 combos × 2 scopes`), ruff + py_compile clean.
- CSV has all 475 ALL-scope combos (+475 paper_real) with `tp,sl,mean_ev,ci_lower,ci_upper,n` plus the capped-convention columns.
- Baseline 1.5/0.5 present; paper_real E.1 metric +0.53% ≈ the +0.48% baseline (sanity check passes).
- Idempotent (re-run overwrites dated outputs); bootstrap seeded (42) for reproducibility.

## 5. Known issues

- **Counterfactual limit (the core caveat):** no intra-trade MFE/MAE → the sweep is
  structurally biased to minimum-SL and cannot recommend a real interior stop. This
  is a property of the data, surfaced honestly, not a script bug.
- **Committed artifacts use a binned snapshot** (binwidth 0.05) pulled read-only,
  because CC has no `DATABASE_URL`. Re-run `--from-db` for exact per-row data; the
  aggregate EV and bootstrap are faithful to within the bin smoothing.
- **EV convention is ambiguous in the directive** (baseline uses `is_win−p`; grid uses
  `±TP/SL`). Both are reported; they are different quantities and not expected to match.
- n drifts as data accrues (snapshot ~1891 vs the earlier 1888/1695 reads).

## 6. What is next

- WARP🔹CMD review. Recommendation: **keep Balanced TP=1.5 / SL=0.5** (the only
  setting with an independent +EV signal on real data) and do NOT cut over to a
  grid-"optimal" corner.
- Open a per-position **MFE/MAE excursion-capture** instrumentation lane — only that
  makes a TP/SL sweep able to find a trustworthy interior optimum. Re-run `--from-db`
  once excursion data accrues.

---

Validation Tier: STANDARD
Claim Level: FOUNDATION
Validation Target: reproducible 475-combo sweep + CI + recommendation; read-only.
Not in Scope: domain/strategy/risk/execution code, migrations, flag flips.
Suggested Next Step: WARP🔹CMD review.
