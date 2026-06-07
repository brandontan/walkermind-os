# TP/SL Calibration Backtest — WARP-83 Sub-Lane E.1

Validation Tier: MINOR (report only — no strategy/runtime code change)
Claim Level: FOUNDATION
Validation Target: Per-profile EV/trade, win rate, max drawdown, and Sharpe-equivalent for the proposed TP/SL bundles, backtested against the settled paper trade history on real data; recommended final TP/SL values for WARP🔹CMD sign-off.
Not in Scope: Changing any strategy default; ev_comparator / scorer_trainer / orchestrator paths; new orderbook capture; new deps/vendor/API keys; building E.2.
Suggested Next Step: WARP🔹CMD sign-off on the final TP/SL values. The Conservative bundle triggers the STOP CONDITION (net negative EV) — this is escalated as a PRODUCT QUESTION below.

---

## STOP CONDITION — TRIGGERED (read first)

The Conservative bundle (TP 60% / SL 30%) produces **NET NEGATIVE expected EV of -6.76% per trade** (a CERTAIN point estimate, not a bound — see methodology). Per the lane STOP CONDITION, no decision is made here. This is escalated as a **PRODUCT QUESTION requiring WARP🔹CMD sign-off**: the strategy is a low-win-rate / fat-right-tail profile (25.6% win rate), and a tight 60% take-profit truncates the very winners that carry the edge, flipping the book negative. A "Conservative" label that loses money is a product contradiction CMD must resolve (rename / re-spec / drop the Conservative tier).

---

## 1. What was built

A reproducible TP/SL calibration backtest over the CrusaderBot settled paper trade history, plus this report. Deliverables:

- `scripts/tpsl_calibration_backtest.py` — a read-only research tool (full type hints, asyncio, no runtime imports) that loads the settled paper cohort from Supabase and computes, per bundle, EV/trade, win rate, max drawdown, and Sharpe-equivalent using a bounded-counterfactual method. It re-derives every number in this report.
- This report, quantifying the three proposed bundles and recommending final values.

No strategy default was changed. No ev_comparator / scorer / orchestrator path was touched.

### Data cohort

- Source: Supabase project `ykyagjdeqcgcktnpdhes`, table `positions`, filter `mode='paper' AND size_usdc>0 AND pnl_usdc IS NOT NULL`.
- n = 1439 settled positions; total stake $8,060; strategy = `late_entry_v3` (1436) + 1 `playbook`; `is_demo=false`.
- The realized policy was TP 1.5 / SL 0.5 on 1386 / 1437 rows — i.e. the proposed **Balanced bundle IS the current live default** (confirmed below).

### Confirming the current hardcoded default (CONFIRM step)

- `domain/strategy/strategies/late_entry_v3.py` defines `DEFAULT_TP_PCT = 0.15` / `DEFAULT_SL_PCT = 0.08`, but these module fallbacks are NOT what ran: the live positions were stamped with TP/SL from the user risk profile / preset, and the dominant realized values are **tp_pct=1.5, sl_pct=0.5** (1386 of 1437 rows). 
- Semantics confirmed empirically: `tp_pct`/`sl_pct` are **return-on-stake thresholds**, not price-move fractions. `sl_hit` trades realize return-on-stake ≈ -0.50 (exactly the SL); `tp_hit` trades realize ≥ +1.50 (the TP, with overshoot). So Balanced = TP +150% of stake / SL -50% of stake = the realized live policy. The webtrader `PROFILE_TP_SL` table in `domain/risk/constants.py` (balanced 0.20/0.15) is a SEPARATE price-move convention and is not the strategy exit policy that generated this data.

---

## 2. Current system architecture

```
positions (Supabase)                          factor_vectors (Supabase)
  entry_price, size_usdc, side,                 entry/open/close_price (ASSET price),
  tp_pct, sl_pct, exit_reason, pnl_usdc,        realized_outcome/_delta, data_source
  opened_at/closed_at, strategy_type            (paper_real 463 / paper_synthetic 1357)
        |                                                  |
        |  (no per-tick price path stored; no MFE/MAE)     | (asset-candle universe,
        v                                                  v  market_id mostly NOT
  scripts/tpsl_calibration_backtest.py  <------------------+  joinable to positions)
     load cohort -> per-trade realized return-on-stake (pnl/stake)
        |
        v  bounded counterfactual per bundle (monotone path reasoning)
     EV/trade, win rate, max drawdown (equity-curve), Sharpe-equiv (mean/sd)
        |
        v
  reports/forge/risk-profile-tpsl-calibration.md  (this report)
```

### Methodology (and its hard limit)

The `positions` table stores only entry_price and the realized exit (exit_reason + pnl_usdc). There is **no stored intra-trade price path** and **no per-trade MFE/MAE excursion table** (verified: no price/tick/candle/snapshot/excursion table exists for the traded binary markets; `strategy_metadata` has no peak fields; `factor_vectors` holds asset-candle prices for a different market universe that does not join to the traded positions). A true re-simulation of a *different* TP/SL is therefore impossible from this data.

What IS recoverable is a **bounded counterfactual** anchored on each trade's realized exit, using monotone path reasoning:

- A `tp_hit` trade (+1.5) provably crossed every threshold below +1.5 on the way up → a **tighter TP is a CERTAIN hit** at that lower level.
- An `sl_hit` trade (-0.5) provably crossed every threshold above -0.5 on the way down → a **tighter SL is a CERTAIN hit** at that lower magnitude.
- A **looser SL** (e.g. -0.75) on an sl_hit trade, or a **higher TP** (e.g. +2.5) on a tp_hit trade, is **UNKNOWABLE** without the path → reported as an explicit optimistic / pessimistic BOUND, never a single number.

Consequence: Conservative (60/30) and every SL=0.5 TP-variation are **CERTAIN point estimates** (both thresholds are tighter than the realized policy → no path uncertainty). The Aggressive bundle (looser SL + higher TP) is genuinely bounded with a wide spread.

Metrics: EV/trade = mean per-trade return on stake; win rate = % of trades with positive counterfactual return; max drawdown = peak-to-trough on the $ equity curve ordered by `opened_at` (per-trade $ = return × stake); Sharpe-equivalent = mean / stdev of per-trade returns (a per-trade ratio, NOT annualised — annualisation is not computable because trade frequency/holding-period normalisation data is not in scope).

---

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/scripts/tpsl_calibration_backtest.py`
- `projects/polymarket/crusaderbot/reports/forge/risk-profile-tpsl-calibration.md`

Modified (state sync):
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

No strategy, risk, ev_comparator, scorer, or orchestrator file was modified.

---

## 4. What is working

### Results table (per profile, settled paper cohort, n=1439)

| Profile (TP / SL) | Scenario | EV / trade | Win rate | Max drawdown | Sharpe-equiv |
|---|---|---|---|---|---|
| Conservative 60% / 30% | certain | **-6.76%** | 25.8% | -$573.34 | -0.176 |
| Balanced 150% / 50% (current default) | certain (= realized) | **+13.0%** | 25.8% | -$153.63 | +0.104 |
| Aggressive 250% / 75% | pessimistic bound | **-3.0%** | 25.8% | -$490.29 | -0.027 |
| Aggressive 250% / 75% | optimistic bound | **+181.7%** | 25.8% | (favorable) | +1.46* |

\* The Aggressive optimistic bound assumes EVERY looser-SL trade recovered to full take-profit — physically implausible; it is an upper bound only, not an estimate. The honest read of Aggressive is "somewhere between -3.0% and +181.7%, undeterminable from available data."

Notes:
- Win rate is identical across bundles at 25.8% because the sign of the per-trade outcome rarely flips under these threshold changes (winners stay winners, losers stay losers); what changes is the *magnitude* captured, which is what drives EV.
- Baseline sanity: realized total PnL = +$1,020.10 on $8,060.05 stake = +12.66% pnl-weighted return, win rate 25.64% — consistent with the Balanced row.

### Why Conservative fails (mechanism)

This strategy makes money from a **fat right tail**: 279 tp_hit trades overshoot to +1.5…+6.8 (avg +2.18) and 59 resolution_win trades pay up to +6.6 (avg +2.49), while losers are bounded near -0.5. Capping the upside at +60% while still losing -30%…-95% on ~74% of trades removes the tail that carries the book. The 30% stop also fires on more trades than the 50% stop saves, deepening drawdown (-$573 vs -$153 for Balanced).

### Alternative-bundle exploration (SL fixed at 0.5, the only SL modellable with certainty)

| Bundle | EV / trade | Sharpe-equiv | Max drawdown | Note |
|---|---|---|---|---|
| TP 60% / SL 50% | -20.5% | n/a | worse | tighter TP destroys edge |
| TP 100% / SL 50% | -11.1% | n/a | worse | still negative |
| TP 150% / SL 50% (Balanced) | +13.0% | +0.104 | -$153.63 | current default — the profitable inflection |
| TP 200% / SL 50% (lower bound) | +9.0% | +0.090 | -$141.97 | LOWER bound; true value likely higher |
| No-TP-cap / SL 50% (lower bound) | **+17.9%** | **+0.148** | **-$121.06** | "let winners run" — best on all three metrics |

The "let winners run / SL 50%" LOWER bound dominates the current default on EV (+17.9% vs +13.0%), Sharpe (+0.148 vs +0.104) AND drawdown (-$121 vs -$154). Because tp_hit trades were force-exited at +1.5, their realized return understates their true peak — so this is a conservative lower bound and the real improvement is likely larger. This is a strong signal that **the current TP=150% may be too tight**, but it requires forward (live-path) validation to confirm, which is exactly why this lane stops for sign-off.

---

## 5. Known issues

- **No intra-trade price path / MFE-MAE data.** This is the irreducible limitation. Conservative and SL=0.5 variations are exact; the Aggressive bundle and any looser-SL or "let-winners-run" recommendation are bounds, not point estimates. Closing this gap requires capturing per-position peak-favorable / peak-adverse excursion going forward (a possible E.2 instrumentation lane — NOT built here).
- **Single TP/SL regime in the data.** 96% of rows ran exactly 1.5/0.5, so the realized sample is concentrated at one operating point; counterfactuals extrapolate from it rather than observing alternative regimes directly.
- **Sharpe is per-trade, not annualised.** Holding-period / trade-frequency normalisation is out of scope; the ratio is comparable across bundles but is not a conventional annualised Sharpe.
- **Cohort is `late_entry_v3`-dominated.** Findings are specific to this strategy's fat-tail return shape; they do not generalise to other strategies.
- **Aggressive optimistic bound is not actionable** — it assumes universal SL recovery; treat only the pessimistic bound (-3.0%) as a floor.

---

## 6. What is next

- WARP🔹CMD sign-off required on final TP/SL values before any E.2 build. This lane STOPS here per the task STOP CONDITION (Conservative negative EV) regardless.
- PRODUCT QUESTION for CMD: the "Conservative" tier (60/30) is net-negative for this strategy. Options: (a) re-spec Conservative to a *wider* SL with capped sizing instead of a tight TP; (b) drop the Conservative tier for late_entry_v3; (c) accept a known-lossmaking conservative tier (not recommended).
- Recommended final values for sign-off (see below).
- If CMD wants the let-winners-run direction validated, a follow-up instrumentation lane should capture per-position MFE/MAE so the bounds collapse to estimates — that is the natural E.2, but it is explicitly NOT built here.

### Recommended final TP/SL values (for CMD sign-off)

- **KEEP Balanced TP 150% / SL 50% as the default.** It is the only proposed bundle that is clearly and certainly positive (+13.0% EV/trade), has the smallest drawdown (-$153) and the only solidly positive Sharpe among the required three.
- **REJECT Conservative 60% / 30%** (-6.76% EV — STOP CONDITION). Escalate the product question above.
- **DO NOT adopt Aggressive 250% / 75% on this data** — the outcome is bounded -3.0% to +181.7% and undeterminable; the pessimistic floor is negative.
- **Optional, data-backed candidate for a future test:** loosen/remove the TP cap while holding SL at 50% (lower-bound EV +17.9%, Sharpe +0.148, drawdown -$121 — beats the current default on every metric). This is a LOWER bound and needs forward MFE/MAE validation before adoption; surfaced for CMD awareness only, not recommended for immediate change.

---

Reproduce: `DATABASE_URL=... python -m crusaderbot.scripts.tpsl_calibration_backtest`
