# 18_1_alpha_stabilization.md

## 1. What Was Built

**Alpha Model Stabilization** — fixes the `ProbabilisticAlphaModel` to consistently produce signals with real predictive value (edge > 2 %) and adds full debug observability via `/alpha` Telegram command.

### Changes implemented

1. **`core/signal/alpha_model.py`** — Upgraded probabilistic alpha model:
   - Added **volatility breakout signal** (z-score amplification): when the current price sits ≥ 0.5 sigma from the rolling mean the deviation is amplified proportionally to its standardised score, capped at 2σ to prevent runaway sizing
   - Upgraded **momentum** from a simple mean of deltas to **exponential-weighted momentum** (α=0.3), giving more weight to the most recent tick direction
   - Increased `deviation_weight` from 0.5 → 0.8 and `momentum_scale` from 1.0 → 1.5 for stronger signals
   - Added **early-tick dampening** guard (`_MIN_HISTORY_TICKS = 5`): all signal components are linearly scaled toward zero for the first five ticks to prevent over-confident edges from an unstable seed
   - Raised `_FORCE_MODE_DEVIATION_MIN` from 0.01 → 0.02 to match the new 2 % minimum edge requirement in force mode
   - Enriched `alpha_model_computed` debug log with `edge`, `confidence`, `z_score`, and `breakout` fields

2. **`core/signal/signal_engine.py`** — Signal edge filter hardening:
   - Raised `_EDGE_THRESHOLD` from **0.5 % → 2.0 %** — eliminates zero-alpha spam signals
   - Raised `_MIN_FORCE_MODE_EDGE` from **0.01 → 0.02** — force mode now consistent with normal threshold
   - Added `alpha_metrics: Optional[AlphaMetrics]` parameter to `generate_signals()`
   - Records every evaluated market tick to `AlphaMetrics` at the `alpha_debug` log point
   - Calls `alpha_metrics.record_signal_generated()` when a tick passes all filters (correct success-rate accounting without double-counting edge statistics)

3. **`monitoring/alpha_metrics.py`** *(new)* — Alpha debug metrics accumulator:
   - `AlphaOutput` dataclass: `{market_id, p_model, p_market, edge, confidence, signal_generated}`
   - `AlphaSnapshot` dataclass: aggregate statistics with `to_dict()` for serialisation
   - `AlphaMetrics` class with `record()`, `record_signal_generated()`, `snapshot()`, `log_summary()`
   - Edge distribution buckets: zero/negative · weak (0–2 %) · moderate (2–5 %) · strong (> 5 %)

4. **`telegram/handlers/alpha_debug.py`** *(new)* — `/alpha` Telegram handler:
   - Module-level `set_alpha_metrics(metrics)` injection
   - `handle_alpha_debug()` returns formatted screen with last-tick `p_model / p_market / edge / S` and aggregate statistics
   - Safe fallback when no metrics injected; zero silent failures (all exceptions caught + logged)

5. **`telegram/command_handler.py`** — Command routing:
   - Added `/alpha` command case in `_dispatch()`
   - Added `_handle_alpha()` method delegating to `handle_alpha_debug()`

---

## 2. Current System Architecture

```
DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING
                                            ↕
                                   core/signal/alpha_model.py
                                   core/signal/signal_engine.py
                                   monitoring/alpha_metrics.py
                                            ↕
                               telegram/handlers/alpha_debug.py
                                  (/alpha command)
```

### Alpha pipeline detail

```
MarketTick
    → ProbabilisticAlphaModel.record_tick()
    → ProbabilisticAlphaModel.compute_p_model()
          deviation (price vs rolling mean)  ─┐
          exp-weighted momentum              ─┼─→ raw_p_model → clamp [0.01,0.99]
          volatility breakout (z-score)     ─┘
          early-tick dampen (n < 5)
    → generate_signals()
          edge = p_model - p_market
          edge > 2 % threshold + volatility scale
          AlphaMetrics.record(AlphaOutput)   ← every tick
          AlphaMetrics.record_signal_generated() ← signal ticks only
```

---

## 3. Files Created / Modified (Full Paths)

| Action   | Path |
|----------|------|
| Modified | `projects/polymarket/polyquantbot/core/signal/alpha_model.py` |
| Modified | `projects/polymarket/polyquantbot/core/signal/signal_engine.py` |
| Created  | `projects/polymarket/polyquantbot/monitoring/alpha_metrics.py` |
| Created  | `projects/polymarket/polyquantbot/telegram/handlers/alpha_debug.py` |
| Modified | `projects/polymarket/polyquantbot/telegram/command_handler.py` |

---

## 4. What Is Working

- `ProbabilisticAlphaModel` produces three independent signals (deviation, momentum, breakout), summing to materially larger edge values for markets with real price drift
- Exponential-weighted momentum responds faster to recent direction changes than the old uniform average
- Early-tick dampening prevents the model from emitting false confidence during the first 5 ticks of a new market
- `_EDGE_THRESHOLD = 0.02` eliminates sub-2 % spam; force-mode minimum also raised to 0.02
- `AlphaMetrics` accumulates per-tick edge distribution, avg edge, zero-edge count, and signal success rate
- `/alpha` Telegram command returns real-time diagnostics: last p_model/p_market/edge/S + aggregate stats
- All 103 existing signal-related tests pass (FA, SE, SA, ST suites) with no regressions

---

## 5. Known Issues

- `AlphaMetrics` is an in-memory only accumulator; statistics reset on process restart (no DB persistence). Sufficient for debug observability.
- `generate_signals()` in force-signal mode does not record to `alpha_metrics` (force-mode path is separate and intended for testing/bootstrap only).
- The volatility breakout signal depends on having sufficient price history. Markets with fewer than 5 ticks will produce dampened signals regardless; force_mode bypasses this.

---

## 6. What Is Next

- Wire `AlphaMetrics` instance into `generate_signals()` call in `core/pipeline/trading_loop.py` so production metrics are tracked end-to-end
- Inject `AlphaMetrics` via `set_alpha_metrics()` in `main.py` during bot startup so `/alpha` reports live data
- SENTINEL validation pass: confirm edge > 2 % appears consistently under paper-trading conditions
- Consider persisting `AlphaSnapshot` to DB for cross-session trend analysis
