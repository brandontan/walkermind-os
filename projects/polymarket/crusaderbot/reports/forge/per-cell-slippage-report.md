# WARP-83 Sub-Lane D — Per-Cell Calibrated Slippage Report

Validation Tier: MINOR
Claim Level: FOUNDATION
Validation Target: a per-cell breakdown of the **calibrated** slippage replay
(Phase 2b) over current `paper_real` settled trades — distribution, decomposition,
and per-cell gate verdict. Report-only; no runtime code.
Not in Scope: LIVE-sizing thresholds (Sub-Lane C); any strategy / sizing / gate
code change.
Suggested Next Step: WARP🔹CMD review alongside Sub-Lane C; feed the per-cell depth /
edge profile into the cutover decision.

---

## 1. What was built

A per-cell decomposition of the Phase 2b calibrated slippage replay, so the
aggregate 6.1% headline can be read cell-by-cell (where erosion concentrates, and
why). Numbers come from the merged calibrated estimator
(`domain/research/slippage_estimator.py`) applied to the `positions × factor_vectors`
join, replicated in SQL against the canonical Supabase project
(`ykyagjdeqcgcktnpdhes`) because CC has no `DATABASE_URL`. DB output treated as
untrusted (coerced / NULL-guarded). Snapshot: current settled `paper_real` data,
n≈541, last ~36 h window (live data still accruing — counts are a moving snapshot).

## 2. Current system architecture

Read-only analytics over already-persisted data — no new components. The replay
math is the merged Sub-Lane B engine (`scripts/replay_with_slippage.py`) on the
Sub-Lane A calibrated model (wired in Phase 2b):

```
total_bps = max(0, spread - 1.0) * 0.5 * 1e4   (complete-set spread, size-independent)
          + 0.02 * sqrt(min(stake/depth, 4)) * 1e4   (sqrt market impact, size-dependent)
          + 0                                   (no live price in replay → 0 adverse move)
cost_usdc = size_usdc * total_bps / 1e4
```

## 3. Files created / modified

- Created: `projects/polymarket/crusaderbot/reports/forge/per-cell-slippage-report.md`
- Modified: `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- Modified: `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

### 4.1 Per-cell calibrated slippage (paper sizing, ~$7 avg notional)

Per-cell `slip %` is `total_slippage ÷ |gross P&L|` — the per-cell convention the
replay engine's `aggregate_by_cell` uses. The **ALL** `slip %` uses the engine's
`overall_gate` convention: `total_slippage ÷ Σ|per-cell gross|` (sum of ABSOLUTE
per-cell gross, so opposite-signed cells don't cancel and mask erosion) = **5.4%**.
For reference, against *net* gross it is 22.37 ÷ 349.94 ≈ 6.4%; both are ≪ 50%. All
rows are one consistent snapshot (n sums to 545).

| Cell | n | avg bps | spread bps | impact bps | gross P&L | slippage $ | adj. P&L | slip % | gate |
|---|---|---|---|---|---|---|---|---|---|
| btc/5m | 257 | 56.7 | 51.9 | 4.8 | +$263.30 | $10.40 | +$252.91 | 3.9% | OK |
| eth/5m | 265 | 59.9 | 52.8 | 7.2 | +$115.30 | $11.29 | +$104.01 | 9.8% | OK |
| btc/15m | 10 | 59.7 | 55.0 | 4.7 | +$4.47 | $0.26 | +$4.21 | 5.8% | OK |
| eth/15m | 9 | 68.8 | 61.1 | 7.7 | −$22.47 | $0.27 | −$22.73 | 1.2% | OK* |
| sol/15m | 4 | 87.7 | 75.0 | 12.7 | −$10.66 | $0.15 | −$10.81 | 1.4% | OK* |
| **ALL** | **545** | **58.7** | **52.7** | **6.1** | **net +$349.94** | **$22.37** | **+$327.59** | **5.4%** | **OK** |

\* eth/15m and sol/15m are net-**losing** cells on tiny samples (n=9, n=4); their low
slippage % is arithmetic against a negative gross, not a sign of health. Slippage
does not rescue a losing cell — it deepens the loss (adj. P&L more negative).

### 4.2 Per-trade slippage distribution (bps) and book depth

| Cell | bps p50 | bps p90 | bps p99 | bps max | depth p50 | depth min | gross edge (bps of notional) |
|---|---|---|---|---|---|---|---|
| btc/5m | 54.4 | 57.2 | 106.1 | 256.5 | 14,510 | 2,816 | +1,436 |
| eth/5m | 56.5 | 63.0 | 112.2 | 207.9 | 7,242 | 510 | +612 |
| btc/15m | 54.5 | 61.8 | 99.4 | 103.5 | 9,268 | 3,294 | +1,038 |
| eth/15m | 57.4 | 110.8 | 112.7 | 112.9 | 3,186 | 1,036 | −5,828 |
| sol/15m | 62.8 | 133.9 | 161.2 | 164.2 | 1,051 | 844 | −6,229 |

### 4.3 Read

- **The complete-set spread cost dominates (~52 of ~59 bps, ~90%) and is
  size-independent.** It reflects the structural Polymarket binary-market cost
  (`yes_ask + no_ask ≈ 1.01`, charged at half the excess over fair 1.0). At paper
  sizing the sqrt-impact term is small (4.8–12.7 bps) because ~$7 against 1k–15k USDC
  books is a negligible participation ratio.
- **Distribution is tight at the median (p50 ≈ 54–63 bps across all cells) with a thin
  high tail** (p99 ≈ 106–161, max up to 256 bps) driven by the shallowest books — the
  outliers are real thin-book trades, correctly penalized by the sqrt-impact term, not
  numerical artifacts.
- **Depth ranks the cells by LIVE headroom:** btc/5m is deepest (p50 14.5k, min 2.8k),
  eth/5m mid (p50 7.2k, min 510), and the 15m / sol cells are shallow (sol/15m p50
  ~1.0k). The thin cells also carry the highest avg slippage (sol/15m 87.7 bps) — but
  they are low-volume and currently net-losing on alpha alone.
- **Edge ranks the cells by LIVE viability:** btc/5m carries the strongest gross edge
  (+1,436 bps of notional), eth/5m far less (+612), and eth/15m / sol/15m are negative.
  Edge ÷ slippage is the real cutover signal (handed to Sub-Lane C).

## 5. Known issues

- **Paper sizing only (~$7).** The size-dependent impact term is therefore tiny; this
  report is NOT a LIVE-sizing assessment. Sub-Lane C re-evaluates at LIVE notional.
- **Snapshot, not fixed window.** Live `paper_real` data is still accruing; counts
  drift between queries (eth/5m moved 263→265 across two runs). Treat n and totals as a
  point-in-time snapshot, not a frozen dataset.
- **Thin-cell samples are tiny** (btc/15m 10, eth/15m 9, sol/15m 4) — per-cell stats
  there are indicative only, not statistically settled.
- Replicated in SQL (no `DATABASE_URL` in CC); an operator `--from-db` run is the
  confirming follow-up.

## 6. What is next

- WARP🔹CMD review.
- Sub-Lane C: convert these per-cell depth/edge profiles into LIVE-sizing cutover gate
  thresholds (binding constraint is eth/5m: low edge + shallow book).
- Re-run on a larger / frozen window once more `paper_real` accrues, to settle the
  thin-cell stats.
