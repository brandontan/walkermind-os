# WARP-78 Orchestrator Cutover — Holdout Report

- Data source: **paper_synthetic (DEMO — template only, not a real cutover signal)**
- Decision criteria: Track C, margin **C2 moderate (+0.015)**, CI-excludes-0=True
- Preset under test: `candle_auto` + rule `auto` (orchestrator) vs precedence router
- Rules compared (canonical): `close_sweep` / `safe_close` / `flip_hunter`
- Model schema v2, train rows 616

> System in paper trading mode. No real capital deployed. When the data source is synthetic/DEMO the numbers below are illustrative — they exist to lock the report format, not to drive a real cutover.

## 1. Sample size

| Cell | Settled | Holdout | Decided | Abstain | Undecidable |
|---|--:|--:|--:|--:|--:|
| `BTC/5m` | 220 | 66 | 66 | 0 | 0 |
| `BTC/15m` | 220 | 66 | 66 | 0 | 0 |
| `ETH/5m` | 220 | 66 | 66 | 0 | 0 |
| `ETH/15m` | 220 | 66 | 66 | 0 | 0 |
| **overall** | 880 | 264 | 264 | 0 | 0 |

## 2. EV delta (orchestrator − router)

| Cell | Router EV/trade | Orchestrator EV/trade | Δ | 95% CI | Agreement |
|---|--:|--:|--:|:--:|--:|
| `BTC/5m` | +0.0370 | -0.0056 | -0.0426 | [-0.2048, +0.1196] | 50% |
| `BTC/15m` | +0.0548 | +0.0676 | +0.0127 | [-0.1506, +0.1761] | 47% |
| `ETH/5m` | -0.0722 | +0.0840 | +0.1563 | [+0.0113, +0.3012] | 48% |
| `ETH/15m` | -0.0222 | +0.0265 | +0.0487 | [-0.0969, +0.1943] | 61% |
| **overall** | -0.0007 | +0.0431 | +0.0438 | [-0.0334, +0.1210] | 52% |

## 3. Decision diff matrix (router → orchestrator, where they disagreed)

- `BTC/5m`: `close_sweep`→`flip_hunter`: 5, `flip_hunter`→`close_sweep`: 25, `safe_close`→`close_sweep`: 2, `safe_close`→`flip_hunter`: 1
- `BTC/15m`: `close_sweep`→`flip_hunter`: 1, `flip_hunter`→`close_sweep`: 32, `safe_close`→`close_sweep`: 1, `safe_close`→`flip_hunter`: 1
- `ETH/5m`: `close_sweep`→`flip_hunter`: 6, `flip_hunter`→`close_sweep`: 18, `safe_close`→`close_sweep`: 6, `safe_close`→`flip_hunter`: 4
- `ETH/15m`: `close_sweep`→`flip_hunter`: 1, `flip_hunter`→`close_sweep`: 24, `safe_close`→`flip_hunter`: 1

## 4. Factor contribution (top |weight| moving the orchestrator's pick)

| Cell | `close_sweep` drivers | `flip_hunter` drivers |
|---|---|---|
| `BTC/5m` | `momentum`=+0.307, `spread`=+0.153, `ttl_sec`=+0.099 | `momentum`=-0.307, `spread`=-0.153, `ttl_sec`=-0.099 |
| `BTC/15m` | `momentum`=+0.283, `ttl_sec`=+0.103, `oracle_edge`=+0.081 | `momentum`=-0.283, `ttl_sec`=-0.103, `oracle_edge`=-0.081 |
| `ETH/5m` | `momentum`=+0.319, `oracle_edge`=-0.107, `spread`=-0.090 | `momentum`=-0.319, `oracle_edge`=+0.107, `spread`=+0.090 |
| `ETH/15m` | `momentum`=+0.232, `ttl_sec`=-0.079, `orderbook_depth_usdc`=+0.074 | `momentum`=-0.232, `ttl_sec`=+0.079, `orderbook_depth_usdc`=-0.074 |

## 5. Cell-level safety check (Track C catastrophic gate)

Catastrophic if cell Δ ≤ -0.020 OR cell orchestrator EV ≤ -0.050.

| Cell | Δ | Orchestrator EV/trade | Status |
|---|--:|--:|:--:|
| `BTC/5m` | -0.0426 | -0.0056 | ❌ CATASTROPHIC |
| `BTC/15m` | +0.0127 | +0.0676 | ✅ OK |
| `ETH/5m` | +0.1563 | +0.0840 | ✅ OK |
| `ETH/15m` | +0.0487 | +0.0265 | ✅ OK |

## 6. Final recommendation

### ❌ FAIL

| Gate | Result | Detail |
|---|:--:|---|
| margin | ✅ | Δ=+0.0438 vs ≥+0.015 (C2 moderate (+0.015)) |
| ci_excludes_zero | ❌ | 95%CI=[-0.0334, +0.1210] |
| sample_minimums | ✅ | all cells ≥200/60/40 |
| no_catastrophic_cell | ❌ | BTC/5m(Δ=-0.0426, ev=-0.0056) |

→ Orchestrator stays inactive; precedence router retained. Phase 3 iterates (label / factor work) before re-proposing.

