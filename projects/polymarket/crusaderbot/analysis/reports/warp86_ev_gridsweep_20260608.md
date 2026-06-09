# WARP-86 Phase 0a — TP/SL EV Grid-Sweep

Generated: 2026-06-08 09:35 Asia/Jakarta · Data source: binned snapshot warp86_settled_histogram.csv (binwidth 0.05)
SCORER_ACTIVE / ORCHESTRATOR_ACTIVE / ENABLE_LIVE_TRADING: UNTOUCHED (read-only analysis).

## Data

- Source table: `factor_vectors` settled rows (realized_outcome IS NOT NULL AND entry_side IS NOT NULL AND entry_price IS NOT NULL). NOT `positions` (no `realized_outcome` column; wiped for clean-test start).
- ALL scope n = **1891** (>= 1445 baseline target). win-rate = **0.6795**.
- paper_real scope n = **764**, win-rate = **0.7016** (the decision-relevant real-data subset; paper_synthetic is the WARP-77 negative-EV seed and dilutes ALL).

## Baseline reconciliation (E.1 convention: mean(is_win - entry_price))

- ALL: **+0.0002** (+0.02%).
- paper_real: **+0.0053** (+0.53%) — approximately reproduces the E.1 #1684 baseline (+0.48%, n=1445 snapshot); the full ALL set is near-zero because the paper_synthetic seed is slightly -EV.

Note: this E.1 metric is entry-price-relative and is a DIFFERENT quantity from the TP/SL grid EV below (which is a +TP/-SL return). They are not expected to be equal; the grid's 1.5/0.5 cell (convention A) is **+0.8591** with 95% CI [+0.8189, +0.8993].

## Grid sweep (scope = ALL, 475 combos)

**Top-10 by mean_ev (A)**

| # | TP | SL | mean_ev (A) | 95% CI (A) | mean_ev_capped (B) |
|---|----|----|-------------|------------|--------------------|
| 1 | 2.90 | 0.10 | +1.9386 | [+1.8783, +1.9989] | +0.0578 |
| 2 | 2.90 | 0.15 | +1.9226 | [+1.8612, +1.9839] | +0.0418 |
| 3 | 2.90 | 0.20 | +1.9066 | [+1.8442, +1.9689] | +0.0257 |
| 4 | 2.90 | 0.25 | +1.8905 | [+1.8272, +1.9539] | +0.0097 |
| 5 | 2.90 | 0.30 | +1.8745 | [+1.8102, +1.9389] | -0.0063 |
| 6 | 2.80 | 0.10 | +1.8707 | [+1.8123, +1.9290] | +0.0577 |
| 7 | 2.90 | 0.35 | +1.8585 | [+1.7931, +1.9238] | -0.0223 |
| 8 | 2.80 | 0.15 | +1.8546 | [+1.7953, +1.9139] | +0.0417 |
| 9 | 2.90 | 0.40 | +1.8425 | [+1.7761, +1.9088] | -0.0384 |
| 10 | 2.80 | 0.20 | +1.8386 | [+1.7783, +1.8989] | +0.0256 |

**Top-10 by CI lower bound (A) — most robustly positive**

| # | TP | SL | mean_ev (A) | 95% CI (A) | mean_ev_capped (B) |
|---|----|----|-------------|------------|--------------------|
| 1 | 2.90 | 0.10 | +1.9386 | [+1.8783, +1.9989] | +0.0578 |
| 2 | 2.90 | 0.15 | +1.9226 | [+1.8612, +1.9839] | +0.0418 |
| 3 | 2.90 | 0.20 | +1.9066 | [+1.8442, +1.9689] | +0.0257 |
| 4 | 2.90 | 0.25 | +1.8905 | [+1.8272, +1.9539] | +0.0097 |
| 5 | 2.80 | 0.10 | +1.8707 | [+1.8123, +1.9290] | +0.0577 |
| 6 | 2.90 | 0.30 | +1.8745 | [+1.8102, +1.9389] | -0.0063 |
| 7 | 2.80 | 0.15 | +1.8546 | [+1.7953, +1.9139] | +0.0417 |
| 8 | 2.90 | 0.35 | +1.8585 | [+1.7931, +1.9238] | -0.0223 |
| 9 | 2.80 | 0.20 | +1.8386 | [+1.7783, +1.8989] | +0.0256 |
| 10 | 2.90 | 0.40 | +1.8425 | [+1.7761, +1.9088] | -0.0384 |

## Recommendation (Phase 0b)

**Do NOT cut over to a grid-'optimal' TP/SL. The sweep cannot identify a robust interior setting from settlement outcomes alone.**

1. EV is strictly monotone-decreasing in SL under both conventions, so the headline 'optimum' is always the minimum-SL / maximum-TP corner (TP=2.90, SL=0.10). This is an ARTIFACT of the missing intra-trade price path (no per-position MFE/MAE) — the model never sees a winner that a tight SL would have stopped out first, so it systematically under-prices the stop. It is not evidence the stop should be dropped (PROJECT_STATE KNOWN ISSUES: looser-SL bundles are BOUNDED, not point-estimable).
2. Convention B (entry-price-capped) shows TP is largely inert here: the winners are heavy favourites (entry price ~0.9+), whose settlement ceiling (1-p)/p is small, so a large TP is unreachable and adds ~0. Raising TP past ~0.5 buys almost nothing on this population.
3. The only robustly-signed, model-independent quantity is the win-rate (~0.68) and the E.1 baseline EV sign (positive on paper_real, ~0 on the synthetic-diluted ALL).

**Action:** keep Balanced **TP=1.5 / SL=0.5** (the only setting with an independent +EV signal on real data); open an instrumentation lane to capture per-position peak-favourable / peak-adverse excursion going forward — only that makes a TP/SL sweep able to find a real interior optimum. Re-run this sweep `--from-db` once excursion data accrues.

## Method

- 25 TP x 19 SL = 475 combos. Bootstrap n=1000 (seed 42), shared resample indices across combos for comparable CIs; 95% percentile interval.
- Convention A: win -> +TP, loss -> -SL. Convention B: win -> min(TP, (1-p)/p), loss -> -SL.
- Win: YES entry wins on realized_outcome=UP; NO entry wins on DOWN.
- Committed artifacts generated from the read-only binned snapshot (binwidth 0.05); `--from-db` uses exact per-row data.
