# WARP-72 Phase 2 — EV-label retrain + EV A/B (for WARP🔹CMD cutover decision)

- Validation Tier: STANDARD (offline retrain + analysis; no runtime/selection change)
- Claim Level: NARROW INTEGRATION
- Generated: 2026-06-05 (Asia/Jakarta) from live `factor_vectors` (CrusaderBot Supabase `ykyagjdeqcgcktnpdhes`)
- Training set: settled `outcome_source='open_to_close'`, 5m → **BTC/5m=173, ETH/5m=171**. SOL/5m=0 → skipped (`no_data`).
- `SCORER_ACTIVE` remains **False** (no cutover).

> ## VERDICT: cutover criterion NOT met — DO NOT flip `SCORER_ACTIVE`.
> On realized **EV/trade out-of-sample (holdout)** the scorer **loses** to the
> router (`ev_delta = −0.065` overall; scorer goes net-negative EV), the opposite
> of its win-rate result. The required `avg_ev(scorer) > avg_ev(router)` is false.

## 1. What changed (per CMD directive)

Training label switched from binary win to **EV**: `ev_label = is_win − entry_price`
(realized per-trade PnL of a 1-unit binary position — a win pays `1 − entry_price`,
a loss pays `−entry_price`). Entry price per rule: favorites pay `fav_price`; the
underdog `flip_hunter` pays the binary complement `1 − fav_price` (the cheap side
it enters). `MIN_FACTOR_STD` guard retained. The A/B comparison metric is now
**avg EV/trade**, not win-rate.

## 2. EV-trained weights (per cell)

```
BTC/5m  close_sweep  n=173 base_ev=+0.0105 winrate=0.931  top:[oracle_edge=-0.189, ttl_sec=+0.101, spread=-0.088]
        safe_close   n=173 base_ev=+0.0105 winrate=0.931  (== close_sweep; both favorite-side rules)
        flip_hunter  n=173 base_ev=-0.0105 winrate=0.069  top:[oracle_edge=+0.189, ttl_sec=-0.101, spread=+0.088]
ETH/5m  close_sweep  n=171 base_ev=+0.0332 winrate=0.930  top:[oracle_edge=-0.195, momentum=+0.064, ttl_sec=+0.020]
        flip_hunter  n=171 base_ev=-0.0332 winrate=0.070  top:[oracle_edge=+0.195, momentum=-0.064, ttl_sec=-0.020]
```

Favorites are marginally **+EV** in-sample, the underdog marginally **−EV** — but
the margins are tiny and, as §4 shows, do not generalize.

## 3. EV A/B — avg EV/trade (the cutover metric)

In-sample (scorer trained + evaluated on all rows):
```
cell           n   router_ev   scorer_ev   ev_delta  abstain
BTC/5m       113     +0.0017     +0.0112    +0.0096       60
ETH/5m       121     +0.0016     +0.0240    +0.0225       50
ALL          234     +0.0016     +0.0179    +0.0162      110
```

**Holdout (train 70% / test 30% per cell — the honest read):**
```
cell           n   router_ev   scorer_ev   ev_delta  abstain
BTC/5m        33     +0.0406     +0.0158    -0.0248       19
ETH/5m        40     +0.0467     -0.0517    -0.0985       12
ALL           73     +0.0440     -0.0212    -0.0652       31
```

In-sample the scorer looks +EV; **out-of-sample it is −EV vs the router on every
cell** (and net-negative EV outright on ETH and overall). Classic small-sample
overfitting of the per-cell factor weights.

(EV denominator integrity: every compared row had a valid `fav_price`
[range 0.52–0.999, 0 nulls], so `n_ev_compared == n_compared` and the avg-EV
figures are undiluted. The A/B divides EV sums by `n_ev_compared` so an
EV-undecidable row could never drag the average toward zero — Gemini review,
PR #1620.)

## 4. Why win-rate said "ship" and EV says "don't"

For contrast, the **win-rate** holdout (same run) still favors the scorer
(+0.364 BTC / +0.100 ETH / +0.219 overall). The divergence is the whole point of
the EV directive:
- The win-rate scorer prefers the **favorite** side (wins 93% at open→close) and
  abstains from / down-ranks `flip_hunter`'s **cheap underdog** entries.
- Those underdog entries are priced ~0.07 and pay ~0.93 on a win — a ~7% hit-rate
  there is roughly break-even-to-+EV. Dropping them **raises win-rate but lowers
  realized EV**. Out-of-sample the scorer's selection earns **less** EV than the
  router's, and turns negative.

## 5. Statistical caveat (don't over-read either direction)

Per-trade EV payoffs are ≈ ±0.9, so the standard error of avg EV over n≈35
compared trades is ≈ `0.9/√35 ≈ 0.15`. The holdout `ev_delta` magnitudes
(−0.025 … −0.099) are **within that noise band** — so the honest statement is
"**no evidence the scorer beats the router on EV; point estimate favors the
router**," not "the scorer is proven worse." Either way the cutover gate
(scorer > router) is **not** met, and the dataset is far too small/noisy on the
EV metric to justify replacing the router.

## 6. Recommendation (CMD decides)

1. **Do NOT flip `SCORER_ACTIVE`.** Keep the precedence router controlling
   selection. The EV evidence does not support cutover; win-rate alone would have
   been the wrong gate.
2. Keep the scorer in **shadow**; keep accruing `factor_vectors`. Re-run this EV
   A/B when each cell has materially more settled rows (target a few hundred+ per
   cell so the ±0.9-payoff variance shrinks), ideally with a significance test on
   `ev_delta`.
3. The EV-trained weights are committed as the current shadow model (methodology
   is the correct EV target); selection authority remains unbuilt + off.

## 7. Files

- `config/scorer_weights.json` — retrained on the **EV label** (`label_type: "ev"`;
  per-rule `base` = mean EV, `base_winrate` kept informational).
- `domain/strategy/scorer.py` — `rule_entry_price` + `rule_ev`; `score_rule` reads `base`.
- `domain/strategy/scorer_trainer.py` — EV label in `derive_cell`; `LABEL_TYPE="ev"`.
- `domain/strategy/scorer_ab.py` — avg-EV/trade comparison + `format_ev_report`.
- `reports/forge/smart-strike-scorer-ev-ab.md` — this report.
