# WARP-78 Orchestrator Cutover — Holdout Report

- Data source: **paper_synthetic (DEMO — template only, not a real cutover signal)**
- Cutover scope: **BTC/5m, ETH/5m** (15m dropped — Polymarket discontinued the updown-15m series)
- Decision criteria: Track C, margin **C2 moderate (+0.015)**, CI-excludes-0=True
- Preset under test: `candle_auto` + rule `auto` (orchestrator) vs precedence router
- Rules compared (canonical): `close_sweep` / `safe_close` / `flip_hunter`
- Model schema v2, train rows 616

> System in paper trading mode. No real capital deployed. When the data source is synthetic/DEMO the numbers below are illustrative — they exist to lock the report format, not to drive a real cutover.

## 1. Sample size

| Cell | Settled | Holdout | Decided | Abstain | Undecidable |
|---|--:|--:|--:|--:|--:|
| `BTC/5m` | 220 | 66 | 66 | 0 | 0 |
| `ETH/5m` | 220 | 66 | 66 | 0 | 0 |
| **overall** | 440 | 132 | 132 | 0 | 0 |

## 2. EV delta (orchestrator − router)

| Cell | Router EV/trade | Orchestrator EV/trade | Δ | 95% CI | Agreement |
|---|--:|--:|--:|:--:|--:|
| `BTC/5m` | +0.0370 | -0.0056 | -0.0426 | [-0.2048, +0.1196] | 50% |
| `ETH/5m` | -0.0722 | +0.0840 | +0.1563 | [+0.0113, +0.3012] | 48% |
| **overall** | -0.0176 | +0.0392 | +0.0568 | [-0.0528, +0.1665] | 49% |

## 3. Decision diff matrix (router → orchestrator, where they disagreed)

- `BTC/5m`: `close_sweep`→`flip_hunter`: 5, `flip_hunter`→`close_sweep`: 25, `safe_close`→`close_sweep`: 2, `safe_close`→`flip_hunter`: 1
- `ETH/5m`: `close_sweep`→`flip_hunter`: 6, `flip_hunter`→`close_sweep`: 18, `safe_close`→`close_sweep`: 6, `safe_close`→`flip_hunter`: 4

## 4. Factor contribution (top |weight| moving the orchestrator's pick)

| Cell | `close_sweep` drivers | `flip_hunter` drivers |
|---|---|---|
| `BTC/5m` | `momentum`=+0.307, `spread`=+0.153, `ttl_sec`=+0.099 | `momentum`=-0.307, `spread`=-0.153, `ttl_sec`=-0.099 |
| `ETH/5m` | `momentum`=+0.319, `oracle_edge`=-0.107, `spread`=-0.090 | `momentum`=-0.319, `oracle_edge`=+0.107, `spread`=+0.090 |

## 5. Cell-level safety check (Track C catastrophic gate)

Catastrophic if cell Δ ≤ -0.020 OR cell orchestrator EV ≤ -0.050.

| Cell | Δ | Orchestrator EV/trade | Status |
|---|--:|--:|:--:|
| `BTC/5m` | -0.0426 | -0.0056 | ❌ CATASTROPHIC |
| `ETH/5m` | +0.1563 | +0.0840 | ✅ OK |

## 6. Final recommendation

### ❌ FAIL

| Gate | Result | Detail |
|---|:--:|---|
| margin | ✅ | Δ=+0.0568 vs ≥+0.015 (C2 moderate (+0.015)) |
| ci_excludes_zero | ❌ | 95%CI=[-0.0528, +0.1665] |
| sample_minimums | ✅ | all scoped cells ≥200/60/40 |
| no_catastrophic_cell | ❌ | BTC/5m(Δ=-0.0426, ev=-0.0056) |

→ Orchestrator stays inactive; precedence router retained. Phase 3 iterates (label / factor work) before re-proposing.

