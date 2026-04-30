# PHASE 6 COMPLETE — PolyQuantBot EV-Aware Production Alpha Engine
> Date: 2026-03-29
> Branch: `feature/forge/polyquantbot-phase6-final`
> Status: ✅ COMPLETE — paper trading mode
> Predecessor: Phase 5 (multi-strategy edge engine)

---

## What Was Built in Phase 6

Phase 6 transforms Phase 5's edge engine into a **production-grade alpha and execution system** with four new components:

| Component | Role |
|-----------|------|
| **CorrelationEngine** | Bayesian log-odds signal adjustment — prevents probability vanishing |
| **CapitalAllocator** | Score-weighted sizing with hard 10% cap + position-count gate |
| **MarketMaker** | Toxicity-aware async quote placement with non-blocking cancellation |
| **ExecutionEngine (Phase 6)** | EV-based decision tree (TAKER/MAKER/HYBRID/REJECT) with dynamic cost model |

Plus new supporting infrastructure:

- `config/execution_config.py` — frozen dataclass with all execution parameters
- `engine/pipeline_handlers.py` — Phase 6 wiring: CorrelationEngine in `handle_market_data`, CapitalAllocator + ExecutionEngine in `handle_signal`
- `engine/runner.py` — Phase 6 main loop with MM background task support

---

## System Architecture

```
Runner (main loop)
  │
  ├── fetch_markets()            ← Polymarket Gamma REST API
  │
  ├── EventBus (publish MARKET_DATA)
  │     │
  │     ├── handle_market_data
  │     │     ├── run_all_strategies()       ← asyncio.gather (4 strategies)
  │     │     └── CorrelationEngine.adjust_all()
  │     │           ├── Per-signal: lo_posterior = lo_prior + Σ(corr_ij × Δlo_j) / (1+n)
  │     │           └── Recomputes EV with adjusted p_model
  │     │           → publishes SIGNAL (with adjusted p_model, ev)
  │     │
  │     ├── handle_signal
  │     │     ├── Exposure guard (max_total_exposure_pct)
  │     │     ├── CapitalAllocator.allocate()
  │     │     │     ├── weight = score_i / Σ scores  (score floor = 1e-9)
  │     │     │     ├── size   = balance × weight
  │     │     │     └── hard cap: min(size, balance × 0.10)
  │     │     └── ExecutionEngine.decide()
  │     │           ├── Liquidity cap: min(size, volume × 0.10)
  │     │           ├── Lot rounding: Decimal ROUND_DOWN to lot_step
  │     │           ├── expected_cost = slippage + fee + alpha_buffer(volatility)
  │     │           ├── fill_prob     = spread_score × depth_score
  │     │           └── Decision tree:
  │     │                 EV ≤ 0                           → REJECT
  │     │                 EV < expected_cost               → REJECT
  │     │                 spread ≥ 0.02 AND fill_prob ≥ 0.6 → MAKER
  │     │                 EV > cost × 2.0                  → TAKER
  │     │                 else                             → HYBRID
  │     │           → publishes POSITION_SIZED
  │     │
  │     ├── handle_position_sized
  │     │     └── ExecutionEngine.execute()
  │     │           ├── MAKER: asyncio.wait_for(limit order, timeout=3s)
  │     │           ├── TAKER fallback / original TAKER
  │     │           ├── Slippage guard: abort if > 3%
  │     │           └── Partial fill retry (max 1):
  │     │                 remaining = round(unfilled, 6) → Decimal ROUND_DOWN
  │     │                 abort if remaining < min_order_size
  │     │                 abort if retry slippage > max_slippage_pct
  │     │           → publishes ORDER_FILLED
  │     │
  │     └── handle_order_filled
  │           └── state.save_trade() → publishes STATE_UPDATED
  │
  ├── exit_monitor_loop (background)
  │     └── TP +10% / SL -5% / TIMEOUT 30min → close_trade → record_trade
  │
  ├── MarketMaker (optional background, disabled by default)
  │     ├── place_quotes(): bid/ask ± spread_pct around mid
  │     ├── Toxicity guard: 3-tick move OR volume_imbalance > 2
  │     └── cancel_all_orders(): asyncio.create_task() [non-blocking]
  │           retry delays: [0.05, 0.1, 0.2]s
  │           race condition: mm_cancel_race_condition logged
  │
  ├── CircuitBreaker: 3 losses / 5 API failures / 1000ms → 120s cooldown
  ├── StrategyManager: score = 0.4×winrate + 0.6×ev_ratio; auto-disable
  ├── PerformanceTracker: SQLite metrics
  └── HealthServer: GET /health → balance, open_positions, cycle, uptime
```

---

## Files Created / Modified

### New in Phase 6

| File | Description |
|------|-------------|
| `phase6/config/execution_config.py` | Frozen `ExecutionConfig` dataclass with all 18 execution parameters |
| `phase6/engine/correlation_engine.py` | `CorrelationEngine` — Bayesian log-odds update, `adjust_signal()` + `adjust_all()` |
| `phase6/engine/capital_allocator.py` | `CapitalAllocator` — score-weighted sizing, hard cap, position gate |
| `phase6/engine/market_maker.py` | `MarketMaker` — toxicity guard, non-blocking cancel, Quote dataclass |
| `phase6/engine/execution_engine.py` | `ExecutionEngine` — `ExecutionDecision` output, `decide()` + `execute()` |

### Updated for Phase 6

| File | Key Changes vs Phase 5 |
|------|------------------------|
| `phase6/engine/pipeline_handlers.py` | `handle_market_data` calls `CorrelationEngine.adjust_all()`; `handle_signal` uses `CapitalAllocator` + `ExecutionEngine.decide()` |
| `phase6/engine/runner.py` | Initializes all 4 new engines; optional MM background loop; resets `trades_this_cycle` per cycle |
| `phase6/config.yaml` | Added `execution`, `capital_allocator`, `correlation`, `market_maker` blocks |
| `phase6/infra/telegram_service.py` | TRADE_OPENED now includes `decision_mode` and `expected_cost` |

### Carried Over Unchanged from Phase 5

| File | Role |
|------|------|
| `engine/event_bus.py` | Async pub/sub backbone |
| `engine/circuit_breaker.py` | Loss / API / latency breaker |
| `engine/health_server.py` | HTTP health endpoint |
| `engine/performance_tracker.py` | SQLite metrics snapshot |
| `engine/state_manager.py` | SQLite state (WAL mode) |
| `engine/strategy_engine.py` | 4 strategy classes + `run_all_strategies` |
| `engine/strategy_manager.py` | Score, enable/disable, weight |
| `core/signal_model.py` | `SignalResult`, `calculate_ev` |
| `core/risk_manager.py` | Fractional Kelly (utility) |
| `core/execution/paper_executor.py` | Simulated fill engine |
| `infra/polymarket_client.py` | Gamma API fetch |

---

## What's Working

### CorrelationEngine
- Log-odds conversion: `lo = log(p/(1-p))` → numerically stable sigmoid inverse
- Normalized Bayesian update: `lo_post = lo_prior + Σ(corr_ij × Δlo_j) / (1+n)`
- Division by `(1+n)` prevents overconfidence from many correlations
- Each adjustment clamped to `±max_corr_adjustment` (default 0.3) to limit single-pair dominance
- Falls back to original signal when no correlations exist (zero-overhead)
- EV recomputed with adjusted `p_model` after update
- Logs `correlation_applied` with before/after values

### CapitalAllocator
- Score floor at `1e-9` prevents zero-weight division errors
- `weight = score_i / Σ scores` (proportional allocation)
- `size = min(balance × weight, balance × 0.10)` hard cap enforced
- Rejects if `open_positions >= 5` (CLAUDE.md rule)
- Rejects if computed size < `min_order_size` ($5.00)
- Handles new strategies with 0 trades (default score 0.1)

### ExecutionEngine
- Dynamic cost model: `expected_cost = slippage_bps/10k + taker_fee + alpha_buffer`
- `alpha_buffer = clamp(base_alpha + spread_vol × scale, 0, max_alpha)` — bounded even at extreme volatility
- `fill_prob = spread_score × depth_score` ∈ [0.0, 1.0]
- Decision tree routes correctly: REJECT → MAKER → TAKER → HYBRID
- Liquidity cap at 10% of market volume
- Adaptive limit price: 30% inside the spread
- Decimal `ROUND_DOWN` to lot_step prevents FP artifacts (4.999999 → 5.0)
- Slippage guard aborts both primary and retry legs if `> max_slippage_pct`
- Max 1 partial fill retry, strict lot rounding, abort if remainder below minimum

### MarketMaker
- 3-tick price move detection via `price_history` ring buffer
- Volume imbalance detection: ratio > 2 in either direction
- Toxicity halt: disables MM for 60s, fires async cancel
- `asyncio.create_task()` for all cancellations — event loop never blocked
- Retry delays `[0.05, 0.1, 0.2]` with idempotent status check
- Race condition (fill during cancel delay) logged as `mm_cancel_race_condition`
- `cleanup()` awaits all pending cancel tasks on shutdown

---

## Known Issues

1. **Correlation matrix is empty** — `correlation_matrix = {}` in pipeline. All `adjust_all()` calls are no-ops for now. Real matrix requires historical market data or live price feed analysis.

2. **Exit price is simulated** — `exit_monitor_loop` uses `random.uniform(-0.04, 0.06)` drift for paper mode. Real exits require live price polling.

3. **MarketMaker disabled by default** — `market_maker.enabled: false` in config. Enable only after live order submission is wired.

4. **Paper mode only** — `ExecutionEngine.execute()` wraps `paper_executor.py`. No live CLOB order placement yet.

5. **StrategyManager state not persisted** — Scores reset to zero on restart. Needs SQLite persistence in Phase 7.

6. **Momentum uses simulated prev price** — Runner injects `p_market ± random(0, 0.01)` as `p_market_prev`. Requires WebSocket tick feed.

---

## What's Next — Phase 7

| Priority | Task |
|----------|------|
| **P0** | WebSocket feed — replace REST poll with Polymarket CLOB WebSocket |
| **P0** | Live CLOB order execution — implement `live_executor.py` via py-clob-client |
| **P1** | Correlation matrix computation — build from live price co-movement |
| **P1** | StrategyManager persistence — save/load stats on restart |
| **P1** | Real exit prices — subscribe to market tick feed for exit monitor |
| **P2** | Backtest harness — validate all 4 strategies + Phase 6 execution on historical data |
| **P2** | Enable MarketMaker — after live order wiring + risk review |
| **P3** | Dashboard — React frontend with live PnL, strategy scores, order flow |

### Phase 7 Done Criteria
```
✓ Live orders executing on Polygon / Polymarket CLOB
✓ WebSocket feed latency < 100ms
✓ Backtest win rate > 70%
✓ 24+ hours error-free in paper mode
✓ SENTINEL review of all risk logic
✓ Founder confirms: "running well ✅"
```
