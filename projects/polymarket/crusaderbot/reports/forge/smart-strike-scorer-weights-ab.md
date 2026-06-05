# WARP-72 Phase 2 — Scorer Weights Derivation + A/B Report (for WARP🔹CMD)

- Validation Tier: STANDARD (analysis artifact + derived weights; no runtime/selection change)
- Claim Level: NARROW INTEGRATION
- Generated: 2026-06-05 (Asia/Jakarta) from live `factor_vectors` (CrusaderBot Supabase, project `ykyagjdeqcgcktnpdhes`)
- Source rows: settled `outcome_source='open_to_close'`, 5m, BTC+ETH — **338 rows** (BTC/5m=170, ETH/5m=168). SOL/5m=0 → skipped (`no_data`). SCORER_ACTIVE remains **False** (no cutover).

> **CUTOVER DECISION IS CMD's.** The numeric cutover criterion is met, but the win-rate edge is dominated by a favorite/underdog asymmetry, not fine-grained factor skill — and win-rate ≠ EV. Read §4 before any `SCORER_ACTIVE=True`. This report does NOT recommend cutover.

## 1. Training run

`scorer_trainer.build_weights` over the 338 settled rows (the exact `--from-db`
pipeline; rows sourced via the authorized Supabase MCP because the app DB pool is
not wired into the execution sandbox — identical math).

```
scorer_trainer_cell_skipped  cell=SOL/5m reason=no_data rows=0
scorer_trainer_cell_derived  cell=BTC/5m n_rows=170 sufficient=True
scorer_trainer_cell_derived  cell=ETH/5m n_rows=168 sufficient=True
```

Derived per-rule (top-3 |weight|, base = hypothetical win-rate in cell):

```
BTC/5m  close_sweep  n=170 base=0.929  oracle_edge=-0.447  liquidity=+0.221  depth=+0.221
        safe_close   n=170 base=0.929  oracle_edge=-0.447  liquidity=+0.221  depth=+0.221
        flip_hunter  n=170 base=0.071  oracle_edge=+0.447  liquidity=-0.221  depth=-0.221
ETH/5m  close_sweep  n=168 base=0.929  oracle_edge=-0.482  liquidity=+0.207  depth=+0.207
        safe_close   n=168 base=0.929  oracle_edge=-0.482  liquidity=+0.207  depth=+0.207
        flip_hunter  n=168 base=0.071  oracle_edge=+0.482  liquidity=-0.207  depth=-0.207
```

## 2. A/B — in-sample (scorer trained on all rows, evaluated on same)

```
cell           n  router_wr  scorer_wr    delta   agree  abstain  undec
BTC/5m       111      0.261      0.730   +0.468   0.225       59      0
ETH/5m       118      0.314      0.695   +0.381   0.229       50      0
ALL          229      0.288      0.712   +0.424   0.227      109      0
```

## 3. A/B — holdout (train 70% per cell, evaluate on held-out 30%) — the honest read

```
cell           n  router_wr  scorer_wr    delta   agree  abstain  undec
BTC/5m        34      0.294      0.765   +0.471   0.206       18      0
ETH/5m        39      0.359      0.538   +0.179   0.308       12      0
ALL           73      0.329      0.644   +0.315   0.260       30      0
```

Out-of-sample, the scorer beats the router by **+0.315** win-rate overall
(BTC +0.471, ETH +0.179), with ≥20 train rows/cell. **The numeric cutover gate
(scorer > router on held-out settled data, ≥20 rows/cell) is met.**

## 4. What the edge actually is (caveats — decision-critical)

1. **It's the favorite/underdog asymmetry, not subtle factor skill.** The favored
   side wins **92.9%** of candles at open→close (both assets). The recorded router
   picks were **~73% `flip_hunter`** (BTC 124/170, ETH 109/168) — the deliberate
   underdog, which wins ~7% at open→close. So the scorer "wins" mainly by
   preferring the favorite side. `oracle_edge` is the dominant learned weight
   (≈±0.45); the rest is the base rate.
2. **Win-rate ≠ EV.** `flip_hunter` enters the *cheap* underdog side on purpose —
   a ~7% win-rate at a ~0.10 entry can be **+EV** (asymmetric payoff). Selecting it
   less often raises win-rate while potentially **lowering profitability**. The
   directive scopes the scorer to win-rate ONLY and never sizing, so this is a
   known boundary — but it means "higher win-rate" here is NOT proof of "more
   profitable bot."
3. **`close_sweep` ≡ `safe_close` in this dataset.** Both are favorite rules
   (entry = `fav_side`), so their hypothetical-win labels — and thus weights/base —
   are identical. The scorer cannot distinguish them; the precedence tie-break
   (close_sweep first) decides. The real choice the scorer learns is
   *favorite vs underdog*.
4. **~⅓ of rows: scorer abstains.** All rows are `oracle_edge_status='computed'`;
   the ADDITIVE Oracle deny-gate denies all three rules on 109/338 rows where
   `oracle_edge` is below every per-preset threshold. Those rows are excluded from
   the comparison (n_compared 229 of 338 in-sample).
5. **The open→close label favors the favorites' framing.** close_sweep/safe_close
   force-exit before close; flip_hunter holds to settlement. The open→close proxy
   therefore understates flip_hunter's designed exit behavior.

## 5. Recommendation (CMD decides)

- **Do NOT flip `SCORER_ACTIVE` on win-rate alone.** Before cutover, run an
  **EV / realized-PnL** comparison (net of the underdog payoff asymmetry +
  fees/slippage) — win-rate superiority that comes from abandoning cheap +EV
  underdog bets could reduce returns.
- Keep accruing the dataset; re-derive periodically (the trainer is idempotent).
- If/when an EV read confirms the scorer ≥ router on **profit**, bring a cutover
  proposal to CMD; the `SCORER_ACTIVE` selection-authority wiring is still unbuilt
  (deliberate).

## 6. Files

- `projects/polymarket/crusaderbot/config/scorer_weights.json` — stub replaced with
  real BTC/5m + ETH/5m weights (SOL/5m skipped).
- `projects/polymarket/crusaderbot/reports/forge/smart-strike-scorer-weights-ab.md` — this report.
