# WARP-78 Phase 0 — SMART STRIKE Scorer EV-Failure Diagnosis (REPORT ONLY)

- Role: WARP•R00T
- Validation Tier: MINOR (diagnostic report; ZERO code / runtime / selection change)
- Claim Level: FOUNDATION (analysis only; no integration)
- Validation Target: explain why the WARP-72 scorer lost on realized EV despite a
  win-rate edge; confirm/reject the favorite-bias hypothesis; recommend fix vs
  re-approach for WARP-78 Phase 1/2 design.
- Not in Scope: any code change, weight retrain, flag flip, or selection wiring.
  `SCORER_ACTIVE` stays False; the precedence router stays in control.
- Source: live `factor_vectors` (CrusaderBot Supabase `ykyagjdeqcgcktnpdhes`),
  read 2026-06-06 — **399 BTC/5m + 398 ETH/5m** settled `open_to_close` rows
  (2.3× the 170/168 the parked 2026-06-05 reports used). SOL/5m still 0.
- Prior art: `reports/forge/smart-strike-scorer-weights-ab.md` (win-rate A/B),
  `reports/forge/smart-strike-scorer-ev-ab.md` (EV A/B), `reports/forge/smart-strike-audit.md`.

---

## 0. Headline

The favorite-bias hypothesis is **CONFIRMED as the scorer's mechanism** but its
**framing in the state file is wrong**. On the now-2.3×-larger sample the favorite
side is **not −EV** — it is marginally **+EV** (+0.0114 BTC / +0.0146 ETH per
trade). The WARP-72 holdout verdict ("scorer LOST −0.021 EV/trade") was a
**small-sample sign-flip artifact**, not evidence that favorites are unprofitable.

The real reason the scorer cannot beat the router on EV is structural, not a bad
weight vector:

1. The favorite/underdog EV edge (~0.012) is **3–4× smaller than the per-cell
   holdout estimation noise** (SE ≈ 0.04). Signal-to-noise < 1 → the sign is
   unstable across splits. No amount of weight-tuning fixes a sub-noise signal.
2. The decision space is **degenerate**: `close_sweep ≡ safe_close` in the data,
   so the "7-factor" model collapses to a **1-bit favorite-vs-underdog** call,
   dominated by `oracle_edge` (which is itself a favorite/underdog proxy).
3. The training **label is biased**: it scores every rule on the `open_to_close`
   proxy, but `close_sweep`/`safe_close` force-exit BEFORE close while
   `flip_hunter` holds to settlement — so the label misrepresents what the rules
   actually realize.
4. **Volatility and Momentum are effectively dead** in the model
   (`volatility_sigma` is a per-asset constant → weight 0; `momentum` appears only
   weakly on ETH). The factors that *could* carry a regime/timing edge contribute
   ~nothing.

Recommendation: **do not revive the per-cell linear scorer as-is.** Fix the label
and the factors FIRST (Phase 1), then move to an EV-comparator with abstain
(Phase 2) — and only with materially more data + a significance test. Detail in §6.

---

## 1. Why win-rate said "ship" and EV said "don't"

The scorer optimizes **selection win-rate**. The favored side wins ~91.5% at
open→close on both assets, so any selector that tilts toward the favorite raises
win-rate. The router, by contrast, picks the deliberate underdog (`flip_hunter`)
on **75–79%** of rows (BTC 315/399, ETH 297/398 — see §3), which wins ~8.5% at
open→close. So the scorer "wins" on win-rate almost entirely by **abandoning the
router's underdog picks for the favorite**.

But win-rate ≠ profit. `flip_hunter` enters the **cheap** side (~0.10) that pays
~0.90 on a win. A low hit-rate on a cheap, high-payoff entry can be break-even or
+EV. Trading those away for an expensive favorite (~0.90 entry, ~0.10 payoff)
**raises hit-rate while surrendering the asymmetric payoff** — exactly the gap
between the two metrics.

---

## 2. Favorite vs underdog EV distribution (fresh sample)

Per-trade realized EV `= is_win − entry_price` (1-unit binary). The favorite pays
`fav_price`; the underdog pays `1 − fav_price`. On a settled binary the two sides
are **exact negatives** (zero-sum identity, fees aside) — confirmed in data:

```
cell      n    avg_fav_price  fav_winrate  fav_EV_mean  fav_EV_std  dog_EV_mean
BTC/5m   399      0.9059        0.9173       +0.01141     0.2404      -0.01141
ETH/5m   398      0.9000        0.9146       +0.01461     0.2430      -0.01461
```

Reading:

- **The favorite is mispriced *upward* by ~1.1–1.5 points** (wins 91.5–91.7% but
  priced ~90.0–90.6%), so favorite-side EV is **marginally positive** and the
  underdog is the exact mirror, marginally negative — the OPPOSITE sign of the
  WARP-72 holdout. On the larger sample, a favorite tilt is **not** EV-destructive.
- **The edge is inside the noise band.** With `fav_EV_std ≈ 0.24`:
  - full-sample SE of mean EV ≈ 0.24/√400 ≈ **0.012** → the +0.011…+0.015 edge is
    ~1 SE (t ≈ 1.0): not statistically distinguishable from zero.
  - WARP-72 holdout had n≈33–40 per cell → SE ≈ 0.24/√35 ≈ **0.041**, which **dwarfs**
    the ~0.012 signal. The reported holdout `ev_delta` of −0.025…−0.099 is well
    within ±1–2 SE of zero. (The EV-AB report estimated SE ≈ 0.15 using the ±0.9
    max payoff; the realized std is 0.24 because favorite wins are small and
    frequent — but the conclusion is identical: the gap is noise.)

So: **favorite-bias is real and is the scorer's whole behavior, but it is neither
the +EV edge the in-sample A/B suggested nor the −EV loss the holdout suggested.
At candle granularity the fav/dog EV difference is ~0 ± noise.** A near-fairly-priced
binary cannot be turned into reliable EV by re-choosing which side to take.

---

## 3. Router pick mix (why the router's EV looked better in holdout)

```
cell      flip_hunter (underdog)   favorite (close_sweep/safe_close)   none
BTC/5m         315 / 399 (79%)              84 / 399 (21%)              0
ETH/5m         297 / 398 (75%)             101 / 398 (25%)              0
```

The router is overwhelmingly an **underdog** strategy. The scorer systematically
flips most of those to the favorite. Because the two sides' EV difference is
sub-noise, on any given 30% holdout slice *either* side can look better — the
WARP-72 split landed where the underdog (router default) was +EV. This is the
mechanical source of "router +0.044 vs scorer −0.021": **selection variance on a
zero-edge decision**, not router skill.

---

## 4. Per-feature decision attribution

From the committed derivations (`smart-strike-scorer-weights-ab.md` win-rate model;
`smart-strike-scorer-ev-ab.md` EV model). Weights are shrunk point-biserial
correlations of each factor with the rule's label:

```
factor              win-rate model        EV model            role
oracle_edge         ±0.447 / ±0.482       ±0.189 / ±0.195     DOMINANT — a fav/dog
                    (BTC / ETH)           (BTC / ETH)         discriminator (sign
                                                              flips fav vs dog rule)
liquidity_usdc      +0.221 / +0.207       small               favorite-side only
orderbook_depth     +0.221 / +0.207       small               co-linear with liquidity
ttl_sec             small                 +0.101 (BTC)         minor timing term
spread              small                 -0.088 (BTC)         minor
momentum            ~0                     +0.064 (ETH only)   NEAR-DEAD
volatility_sigma    0 (forced)            0 (forced)          DEAD — per-asset
                                                              constant, std→0, weight→0
```

Attribution conclusion: **the model is one feature (`oracle_edge`) wearing a
seven-feature costume.** `oracle_edge` is effectively "how favored is the favorite",
so the scorer is re-deriving the favorite/underdog choice it already gets from
`fav_side`. `liquidity`/`depth` are co-linear and only mark the favorite side.
`momentum` and `volatility_sigma` — the two factors WARP-78 Phase 1 wants to make
load-bearing — currently contribute **essentially nothing**. There is no
fine-grained "factor skill" being learned; there is a base rate plus a fav/dog
switch.

---

## 5. Stake / sizing comparison

**Sizing is not the differentiator, and fixing sizing would not fix this.** The
scorer's directive scopes it to selection/win-rate only — it never sizes. The EV
A/B compares both selectors at an identical **1-unit** binary position, so the
router-vs-scorer EV gap is **pure selection**, with zero contribution from stake.

On the router's losing picks vs the scorer's losing picks the realized loss
magnitude differs only by entry side, not by stake:
- a losing **favorite** pick (scorer) costs `−fav_price ≈ −0.90`;
- a losing **underdog** pick (router) costs `−(1−fav_price) ≈ −0.10`.

So the scorer takes **fewer but far larger** losses (rare 0.90 hits) and the router
takes **frequent but tiny** losses (0.10 hits) — the asymmetric-payoff structure,
not sizing. Any future EV work must price this asymmetry directly (the EV label
already does); a uniform stake comparison is the correct, sizing-neutral read and
it still says the scorer has no selection edge.

---

## 6. Recommendation — change approach (do NOT just retune)

The parked scorer's problem is **not** an unlucky holdout or a bad K; it is that
the thing it decides (favorite vs underdog on a ~fairly-priced binary) carries no
reliable EV, the decision space is degenerate, and the label is biased. Retraining
on more rows of the SAME design will keep landing at "no evidence either way."
Recommended sequence for CMD to consider for Phase 1/2:

1. **Fix the label before any new model (correctness, not sample size).** Score
   each strategy on its **actual realized exit**, not the `open_to_close` proxy:
   `flip_hunter` → hold-to-settlement; `close_sweep`/`safe_close` → force-exit
   price. The current label structurally favors the favorite framing and cannot
   represent what the rules really earn. (Phase 1.4's `data_source` provenance
   column + real-CLOB cutover are prerequisites for trustworthy labels.)

2. **Make Volatility + Momentum real, discriminating measures (WARP-78 Phase 1).**
   They are dead in the current model. If any candle-level EV edge exists, it lives
   in **regime / price-velocity / timing**, not in re-deriving the favorite from
   `oracle_edge`. Measure volatility per-TF/per-asset (not a constant) and momentum
   as actual price velocity (not an `ask_diff` threshold), and check their
   correlation with **realized EV** in shadow before trusting them.

3. **Collapse the degenerate rules or model them by exit behavior.**
   `close_sweep ≡ safe_close` under the current label — either distinguish them by
   their real exit timing/price (ties to #1) or treat the choice explicitly as
   favorite-vs-underdog + a timing model, rather than pretending three independent
   linear rules.

4. **Only then build the EV-comparator (WARP-78 Phase 2)** — per-strategy EV
   estimator → `argmax` → abstain — behind `ORCHESTRATOR_ACTIVE=False`, shadow
   first. Gate cutover on a **significance test** on `ev_delta`, not a point
   estimate: target enough settled rows per cell that SE ≪ the candidate edge
   (current SE ≈ 0.04 ≫ ~0.012 signal → need the edge to grow OR the sample to
   reach the low-thousands per cell, whichever comes first; if the edge stays
   ~0.01 it is not worth trading at this granularity).

5. **Until all the above: keep the precedence router and `SCORER_ACTIVE=False`.**
   The router's underdog tilt is the higher-variance side but, on the full sample,
   **not the worse-EV side** — it is statistically tied. Replacing it now would add
   risk with no measured reward.

### Does this trip a global STOP condition?

Per the mission's STOP list: *"Phase 0 diagnosis reveals scorer framework
fundamentally flawed (may invalidate Phase 1/2 design)."* Partial yes — the
**per-cell linear win/EV scorer framework is not salvageable as-is** (degenerate
rules + biased label + sub-noise edge). But this does **not** invalidate the
mission's Phase 1/2 *direction*; it sharpens it: Phase 1 (elevate Volatility +
Momentum) and Phase 2 (EV-comparator + abstain) are exactly the right next moves,
provided the **label is fixed first** and cutover is gated on significance.
**Flagging to CMD as the Phase 0 STOP handoff** (recommendation, not a unilateral
re-scope) — CMD owns the Phase 1 design decision.

---

## Mandatory FORGE sections

1. **What was built** — none (REPORT ONLY). A data-grounded diagnosis of the
   WARP-72 scorer's EV failure.
2. **Current system architecture** — unchanged. Precedence router controls
   selection; `StrategyScorer` shadow-only, `SCORER_ACTIVE=False`; weights in
   `config/scorer_weights.json` (EV-labelled, 170/168-row derivation).
3. **Files created / modified** —
   `projects/polymarket/crusaderbot/reports/forge/smart-strike-scorer-ev-failure.md`
   (this report); `state/PROJECT_STATE.md` + `state/CHANGELOG.md` (sync).
4. **What is working** — diagnosis complete and reproducible: the favorite/underdog
   EV structure and router pick-mix are confirmed on 797 fresh settled rows; the
   noise analysis explains the win-rate↔EV divergence and the holdout sign-flip.
5. **Known issues** — none introduced. Open: dataset still small per cell for EV
   significance; `volatility_sigma`/`momentum` not yet usable; label uses the
   open→close proxy.
6. **What is next** — CMD reviews this report and decides WARP-78 Phase 1 design
   (the directive's STOP after Phase 0). Suggested first move: fix the realized-EV
   label + give Volatility/Momentum real measurement before any new selector.

- Suggested Next Step: WARP🔹CMD review → approve Phase 1 design (label fix +
  Volatility/Momentum measurement, shadow-only) per §6.
