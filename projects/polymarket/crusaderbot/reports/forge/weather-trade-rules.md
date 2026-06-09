# WARP•FORGE — weather-trade-rules

## 1. What was built

WARP-49 trade rules applied to the WeatherDomainStrategy:

1. **EV formula** corrected to odds-based: `EV = (p_true - price) / price`
   Previously used simple edge `p_true - price`.

2. **Entry filters** (MIN_HOURS / MAX_HOURS / MIN_SIZE):
   - `min_hours_to_expiry` (default 2.0h): skip markets resolving in < 2h
   - `max_hours_to_expiry` (default 72.0h): skip markets > 72h out
   - `min_size_usdc` (default $0.50): skip when Kelly size below minimum order

3. **Trailing stop — Exit 2** (breakeven activation at +20%):
   Reads `high_water_price` from position metadata. When high_water ≥
   entry × 1.20 and current_price < entry, closes at breakeven.
   Requires execution layer to write `high_water_price` into position
   metadata as price updates arrive.

4. **Forecast-change exit — Exit 4** (bucket-membership + adaptive buffer):
   Exits when `|current_mean - bucket_mid| > half_range + 2°F`.
   `half_range = (bucket_high - bucket_low) / 2`. Adaptive to bucket width.
   Falls back to fixed 2°F threshold when bucket bounds missing in metadata.
   Logs new `p_new` (updated bucket probability) in exit metadata.

5. **Exit 5: near-expiry close** — exits within final 2h of market lifetime.

6. **Multi-user forecast cache** (process-level, 5-min TTL):
   `_FORECAST_CACHE` at module level stores `(city, date) → (markets, forecasts)`.
   Subsequent users' scan calls for the same city+date hit the cache instead
   of triggering duplicate API calls.

## 2. Current system architecture

```
signal_scan_job.run_once() [per user]
  └─ WeatherDomainStrategy.scan()
        ├─ _cache_get(city, date)  ← shared cache (first user populates)
        ├─ fetch_weather_markets / fetch_all  (only on cache miss)
        ├─ entry filters: volume, spread, price, bucket, hours, size
        ├─ bucket_prob() → expected_value() [odds-based EV]
        └─ kelly_size() → SignalCandidate [with bucket bounds in metadata]

exit_watcher.registry_strategy_evaluator()
  └─ WeatherDomainStrategy.evaluate_exit(position)
        ├─ Exit 1: stop_loss (20%)
        ├─ Exit 2: trailing_stop_breakeven (requires high_water_price)
        ├─ Exit 3: tp_48h / tp_48h_plus
        ├─ Exit 4: forecast_shift (adaptive bucket + 2°F buffer)
        └─ Exit 5: near_expiry (≤ 2h to close)
```

## 3. Files created / modified

- `projects/polymarket/crusaderbot/strategies/weather/math_utils.py`
  — `expected_value()`: formula changed to `(p_true - price) / price`

- `projects/polymarket/crusaderbot/domain/strategy/strategies/weather.py`
  — `scan()`: added `_hours_to_expiry` import; min/max hours and min_size
    config params; hours filter; min_size gate; multi-user cache logic;
    `hours_to_expiry` in signal metadata
  — `evaluate_exit()`: Exit 2 trailing stop; Exit 4 adaptive forecast-shift;
    Exit 5 near-expiry catch; `bucket_prob` import for p_new in metadata

- `projects/polymarket/crusaderbot/reports/forge/weather-trade-rules.md` (this file)

## 4. What is working

- `ruff check` passes on both files
- EV formula unit-checked: `expected_value(0.6, 0.4) == 0.5` ✓
- Kelly formula unchanged (correct for binary bets)
- Cache logic: asyncio-safe (single-threaded event loop; dict ops atomic)
- All exit paths return typed `ExitDecision`; no silent failures

## 5. Known issues

- **Trailing stop (Exit 2)** is conditional on `high_water_price` being present in
  position metadata. The execution / position-update layer does not yet write
  this field. Exit 2 is a no-op until that field is stored. Tracked separately.
- `_hours_to_expiry` re-imported in `scan()` — shared from `strategies/weather/strategy.py`.

## 6. What is next

- Execution layer: write `high_water_price` to position metadata on each
  price update cycle so Exit 2 becomes active.
- WARP•ECHO: investor/briefer report from this forge output.
- TG profit alert integration.

---

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: entry filters, EV formula, exit rules (1–5) in WeatherDomainStrategy
Not in Scope: execution layer high_water_price tracking, multi-user scan orchestration changes
Suggested Next Step: WARP•SENTINEL validation required before merge.
Source: projects/polymarket/crusaderbot/reports/forge/weather-trade-rules.md
Tier: MAJOR
