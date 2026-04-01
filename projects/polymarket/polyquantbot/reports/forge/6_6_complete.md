# PHASE 6.6 COMPLETE — Final Hardening
> Date: 2026-03-29
> Branch: `feature/forge/polyquantbot-phase6_6-final`
> Status: ✅ COMPLETE
> Backward compatibility: ✅ Phase 6 interfaces unchanged

---

## Objective

Phase 6.6 Final Hardening adds production-grade stability on top of Phase 6's EV-aware
execution system. All changes are **additive patches** — the Phase 6 codebase is untouched.

---

## What Was Built

| Module | Problem Solved | Key Algorithm |
|--------|---------------|---------------|
| `correlation_matrix.py` | Phase 6 used a hand-crafted dict prone to jitter spikes | Rolling Pearson + Ledoit-Wolf shrinkage + EMA smoothing |
| `execution_engine_patch.py` | Phase 6 fill_prob was determinism-free (heuristic) | Physics-inspired `depth_ratio × latency_penalty × spread_penalty` |
| `market_maker_patch.py` | No inventory tracking; MM could accumulate unbounded exposure | Hard stop at `inventory_limit_pct × max_position × hard_stop_multiplier` |
| `exit_engine_patch.py` | Static TP/SL was wrong in low/high vol regimes | Adaptive `tp_pct = clamp(2×vol, 0.02, 0.15)` per position |
| `sizing_patch.py` | Phase 6 CapitalAllocator gave binary reject on correlation | Soft reduction: `size × (1 − min(total_corr, 0.8))` |
| `volatility_filter.py` | No regime awareness in sizing | `if vol > threshold: size × 0.5` |
| `runner_patch.py` | No integration point for all patches | `Phase66Integrator` + `MarketCache` wires all patches |
| `config.yaml` | Phase 6 config missing hardening params | Added `correlation`, `market_maker`, `position` adaptive blocks |

---

## System Architecture (Phase 6.6)

```
MARKET_DATA tick
      │
      ▼
MarketCache.on_tick(market_id, price, latency_ms)
      │  stores: prices deque, log-returns, volatility, latency
      │
      ▼ (every recompute_interval ticks)
CorrelationMatrix.recompute(correlation_id)
      │  rolling Pearson → shrink (factor=0.7) → EMA (α=0.3) → clamp [-1,1]
      │  output: dict[(mkt_a, mkt_b), float]  (same format as Phase 6)
      │
      ▼ (passed to Phase 6 CorrelationEngine.adjust_all() — UNCHANGED)
[Phase 6 pipeline: SIGNAL → FILTERED_SIGNAL → POSITION_SIZED]
      │
      ▼ (Phase 6.6 sizing gate, replaces static config.tp_pct/sl_pct)
VolatilityFilter.apply(size, vol)
      │  vol > 0.03 → size × 0.5
      │
      ▼
SizingPatch.apply(signal_market_id, size, open_positions, corr_matrix)
      │  total_corr = Σ max(corr_i, 0), capped at 1.0
      │  size × (1 − min(total_corr, 0.8))
      │  reject if size < min_order_size
      │
      ▼ (Phase 6.6 fill-prob, passed into ExecutionDecisionV2)
ExecutionEnginePatch.decide_v2(...)
      │  fill_prob = clamp(depth_ratio × latency_penalty × spread_penalty, 0, 1)
      │  decision tree: TAKER / MAKER / HYBRID / REJECT   (same logic as Phase 6)
      │
      ▼ (Phase 6 execute() — UNCHANGED)
[ORDER_FILLED → STATE_UPDATED]
      │
      ▼ (on fill)
MarketMakerPatch.record_fill(market_id, size, outcome)
MarketMakerPatch.check_inventory(market_id, max_position)
      │  max_inventory = 0.2 × max_position × 1.5
      │  if |net_pos| > max_inventory → disable + async cancel_all_orders
      │
      ▼ (on position open)
ExitEnginePatch.compute_levels(market_id, entry_price, returns)
      │  vol = max(stdev(returns[-20:]), 0.01)   [fallback: default_vol=0.02]
      │  tp_pct = clamp(2.0 × vol, 0.02, 0.15)
      │  sl_pct = clamp(1.0 × vol, 0.01, 0.10)
      │  tp_price = entry_price × (1 + tp_pct)
      │  sl_price = entry_price × (1 − sl_pct)
      │
      ▼ (exit monitor loop)
ExitEnginePatch.should_exit(current_price, levels, elapsed_min, timeout)
```

---

## Files Created

```
phase6_6/
├── __init__.py
├── config.yaml                            ← Extended config with all Phase 6.6 params
├── engine/
│   ├── __init__.py
│   ├── correlation_matrix.py              ← Stabilized correlation estimator
│   ├── execution_engine_patch.py          ← Realistic fill-prob model + decision_v2
│   ├── exit_engine_patch.py               ← Adaptive TP/SL from vol
│   ├── market_maker_patch.py              ← Inventory hard stop
│   ├── sizing_patch.py                    ← Soft correlation sizing
│   └── volatility_filter.py              ← Regime-aware size reduction
└── integration/
    ├── __init__.py
    └── runner_patch.py                    ← Phase66Integrator + MarketCache
```

No Phase 6 files were modified.

---

## Detailed Design Decisions

### 1. Correlation Matrix — Shrinkage + EMA

**Problem:** Raw Pearson correlation with short history (30 pts) has high estimation
variance. Single anomalous co-move can spike a coefficient from 0.2 to 0.9 in one cycle.

**Solution:**
- Ledoit-Wolf shrinkage toward identity (factor=0.7): `C_shrunk = 0.3 × C_pearson`
  This reduces noise but preserves directional information.
- EMA smoothing (α=0.3): ~3-cycle half-life. New estimates blend in gradually.
- Minimum data guard: skip pairs with < 30 returns to prevent phantom correlations.
- Orphaned pairs decay by `(1 − α)` per cycle, expiring when < 1e-6.

**Edge cases handled:**
- Constant price series (stdev=0): returns 0.0 correlation.
- Insufficient data: pair skipped entirely (not 0.0 assigned — it decays from prior).
- NaN / inf from statistics.correlation: caught, returns 0.0.

### 2. Fill Probability — Physics Model

**Problem:** Phase 6 `fill_prob = spread_score × depth_score` was heuristic, non-monotone
in latency, and had no connection to actual fill mechanics.

**New formula:**
```
depth_ratio    = min(depth / max(size, 1e-3), 10)          # liquidity vs order size
latency_penalty = exp(−latency_ms × volatility × 0.01)     # time-in-flight risk
spread_penalty  = exp(−spread × 10)                        # market illiquidity
fill_prob       = clamp(depth_ratio × latency_penalty × spread_penalty, 0, 1)
```

- `depth_ratio > 1` means market has more than enough depth → compensates for penalties.
- Capped at 10 to prevent extreme depth masking bad latency.
- Both exp() terms are deterministic (no random) and always ∈ (0, 1].
- Full output clamped to [0, 1].

**Decision tree logic is unchanged from Phase 6** — only fill_prob input changes.

### 3. MM Inventory Hard Stop

**Problem:** Phase 6 MM tracked toxicity (adverse price move) but had no position-level
limit. Net inventory could grow unbounded through a series of filled bids.

**Solution:**
```
max_inventory = inventory_limit_pct × max_position × hard_stop_multiplier
             = 0.2 × (balance × 0.10) × 1.5
             = 0.03 × balance           (e.g., $30 on $1000 account)
```

- `record_fill()` updates net_position after every fill (YES = +size, NO = −size).
- `check_inventory()` is idempotent: re-calling while in cooldown returns `stopped=True`
  without re-triggering cancellations or resetting the timer.
- Cancellation is fire-and-forget via `asyncio.create_task()`.
- Logs `mm_inventory_hard_stop` WARNING on trigger.

### 4. Adaptive Exit Levels

**Problem:** Fixed tp_pct=0.10, sl_pct=0.05 is too wide in quiet markets (missing exits)
and too tight in volatile markets (premature stop-outs).

**Solution:**
```
vol = max(stdev(returns[-20:]), 0.01)    # floor prevents zero-width levels
tp_pct = clamp(2.0 × vol, 0.02, 0.15)
sl_pct = clamp(1.0 × vol, 0.01, 0.10)
```

- Asymmetric multipliers (TP=2×, SL=1×): profit target is wider than stop to maintain
  positive expectancy (TP/SL ratio ≥ 2 when vol is the same for both).
- Both clamped: prevents impossibly tight or unreachably wide levels.
- Fallback to `default_vol=0.02` when < 2 returns available.

### 5. Soft Correlation Sizing

**Problem:** Phase 6 CapitalAllocator rejected if `open_positions >= 5` (binary).
This prevented valid trades with weak positive correlation.

**Solution:**
```
total_corr = min(Σ max(corr_i, 0), 1.0)     # only positive, capped at 1.0
adjusted   = size × (1 − min(total_corr, 0.8))
```

- Max 80% reduction: even fully correlated portfolio still allows 20% of original size.
- Negative correlations ignored (hedging is not free leverage in this model).
- Binary rejection still applies if `adjusted < min_order_size`.

### 6. Volatility Filter

Simple, last-gate check:
```
if vol > high_vol_threshold (0.03):
    size × 0.5
```

- Applied before correlation sizing so both reductions compound correctly.
- Configurable threshold and factor.

---

## Configuration Changes (config.yaml)

```yaml
correlation:
  window: 50               # NEW: rolling window size
  min_data_points: 30      # NEW: minimum data before correlation
  recompute_interval: 10   # NEW: recompute every 10 ticks
  threshold: 0.7           # NEW: significant correlation cutoff
  shrinkage_factor: 0.7    # NEW: Ledoit-Wolf shrinkage
  ema_alpha: 0.3           # NEW: EMA smoothing

market_maker:
  inventory_limit_pct: 0.2    # NEW
  hard_stop_multiplier: 1.5   # NEW
  cooldown_seconds: 60        # (was present, now drives MM patch too)

execution:
  high_vol_threshold: 0.03    # NEW: volatility regime threshold

position:
  default_vol: 0.02           # NEW: fallback when no return history
  tp_vol_multiplier: 2.0      # NEW: tp_pct = clamp(2*vol, tp_min, tp_max)
  sl_vol_multiplier: 1.0      # NEW: sl_pct = clamp(1*vol, sl_min, sl_max)
  tp_min: 0.02                # NEW
  tp_max: 0.15                # NEW
  sl_min: 0.01                # NEW
  sl_max: 0.10                # NEW
```

---

## Structured Log Events Added

| Event | Level | Module | Key Fields |
|-------|-------|--------|------------|
| `correlation_update` | INFO | correlation_matrix | pairs_computed, markets_eligible, shrinkage_factor, ema_alpha |
| `fill_probability_calculated` | INFO | execution_engine_patch | fill_prob, depth_ratio, latency_penalty, spread_penalty |
| `mm_inventory_hard_stop` | WARNING | market_maker_patch | net_position, max_inventory, cooldown_until, hard_stop_count |
| `mm_inventory_already_halted` | DEBUG | market_maker_patch | cooldown_remaining_s |
| `mm_inventory_updated` | DEBUG | market_maker_patch | delta, net_position |
| `adaptive_exit_levels` | INFO | exit_engine_patch | tp_price, sl_price, tp_pct, sl_pct, vol, vol_source |
| `sizing_adjustment` | INFO | sizing_patch | original_size, adjusted_size, total_corr, reduction_factor |
| `sizing_rejected_correlation` | WARNING | runner_patch | total_corr, reason |
| `volatility_filter_applied` | DEBUG | volatility_filter | regime, reduction_applied, original_size, adjusted_size |
| `sizing_rejected_volatility_filter` | WARNING | runner_patch | regime, original_size |
| `execution_decision_v2` | INFO | execution_engine_patch | mode, fill_prob, latency_ms, volatility |
| `phase66_integrator_created` | INFO | runner_patch | all config params |

All log events include `correlation_id` for end-to-end tracing.

---

## Known Issues / Limitations

1. **No numpy dependency** — correlation uses `statistics.correlation` (stdlib).
   For large market counts (>100), this may be slower than numpy; acceptable for ≤50 markets.

2. **CorrelationMatrix is single-threaded** — designed for asyncio; no thread safety.

3. **MM inventory uses USD size** — Polymarket uses share/token quantities; size conversion
   (USD → shares via price) must be done by the caller before `record_fill()`.

4. **ExitEnginePatch stores no state** — exit levels must be persisted by the caller
   (e.g., stored as `tp_price`, `sl_price` columns on the trade in StateManager).

5. **Volatility filter is last-write-wins** — if `vol_filter` and `sizing_patch` both
   reduce size, the combined effect is `size × 0.5 × (1 − total_corr)`. This is
   intentional but conservative.

6. **Phase 6 CorrelationEngine still uses the dict** — CorrelationMatrix.get_matrix()
   returns the same `{(mkt_a, mkt_b): float}` format, so it plugs in directly.
   However, Phase 6 CorrelationEngine still applies its log-odds adjustment on top.
   If double-adjustment is undesired, replace the dict passed to `adjust_all()`.

---

## What's Next — Phase 7

| Task | Description |
|------|-------------|
| **Live CLOB order submission** | Replace `execute_paper_order` with `py-clob-client` POST calls |
| **Real depth feed** | Subscribe to CLOB WebSocket for actual book depth (replace `market_ctx["depth"]` estimate) |
| **Real latency measurement** | Measure per-request RTT and pass to `on_market_tick(latency_ms=...)` |
| **StateManager exit levels** | Add `tp_price`, `sl_price` columns to `trades` table |
| **MM live quoting** | Enable `market_maker.enabled: true` with live CLOB limit orders |
| **Backtest validation** | Run Phase 6.6 sizing + exit logic on historical Gamma data |
| **Dashboard update** | Show per-strategy correlation matrix, regime status, inventory levels |
