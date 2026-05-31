# WARP•FORGE — weather-strategy-metadata

## 1. What was built

Persistence + replay of opaque per-strategy signal metadata through the
trading execution chain, so a weather position's scan-time snapshot (city,
bucket bounds, entry forecast mean) rides with the position and is handed back
to the strategy's `evaluate_exit` hook. This activates **Exit 4 (adaptive
forecast-shift)** in the weather strategy, which previously fell back to a
graceful no-op because the exit payload lacked `city` / `bucket_low` /
`bucket_high` / `mean_tmax_f`.

New DB column `positions.strategy_metadata JSONB` (migration 076) carries the
data; the existing `SignalCandidate.metadata` dict is the source.

## 2. Current system architecture

```
WeatherDomainStrategy.scan()
  └─ SignalCandidate.metadata {city, bucket_low/high, mean_tmax_f, end_date, ...}
        │
  signal_scan_job._build_trade_signal()
  └─ TradeSignal.strategy_metadata = cand.metadata
        │
  TradeEngine.execute() → router.execute() → router._paper()
  └─ paper.execute(strategy_metadata=...)
        └─ INSERT INTO positions (..., strategy_metadata) VALUES (..., $12::jsonb)
               with json.dumps(strategy_metadata)
        │
  exit_watcher tick → registry.list_open_for_exit()
  └─ _OPEN_FOR_EXIT_COLS selects p.strategy_metadata
        └─ _row_to_open_position(): _loads_jsonb() → OpenPositionForExit.strategy_metadata
               │
  exit_watcher.registry_strategy_evaluator()
  └─ if name == "weather": payload.update(position.strategy_metadata)
        └─ WeatherDomainStrategy.evaluate_exit(payload)
               └─ Exit 4 reads city / bucket_low / bucket_high / mean_tmax_f
```

JSONB convention (no pool-level asyncpg codec): write `json.dumps()` + `$N::jsonb`
cast; read `json.loads()` via `_loads_jsonb()` helper. Matches the
`system_alerts.metadata` pattern from migration 072.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/migrations/076_positions_strategy_metadata.sql` (new)
  — `ALTER TABLE positions ADD COLUMN IF NOT EXISTS strategy_metadata JSONB DEFAULT NULL`
- `projects/polymarket/crusaderbot/services/trade_engine/engine.py`
  — `TradeSignal.strategy_metadata: Optional[dict] = None`; forwarded in `execute()` router call
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py`
  — `_build_trade_signal`: `strategy_metadata=(cand.metadata or None)`
- `projects/polymarket/crusaderbot/domain/execution/router.py`
  — `execute()` + `_paper()` thread `strategy_metadata` through to `paper.execute`
- `projects/polymarket/crusaderbot/domain/execution/paper.py`
  — `execute(strategy_metadata=...)`; INSERT column + `$12::jsonb` + `json.dumps`
- `projects/polymarket/crusaderbot/domain/positions/registry.py`
  — `OpenPositionForExit.strategy_metadata`; `_OPEN_FOR_EXIT_COLS` selects it;
    new `_loads_jsonb()` helper; `_row_to_open_position` maps it
- `projects/polymarket/crusaderbot/domain/execution/exit_watcher.py`
  — `registry_strategy_evaluator` weather block spreads `strategy_metadata` into payload
- `projects/polymarket/crusaderbot/tests/test_weather_strategy_metadata.py` (new) — 16 hermetic tests
- `projects/polymarket/crusaderbot/reports/forge/weather-strategy-metadata.md` (this file)

## 4. What is working

- 16 new hermetic tests pass (TradeSignal field, `_loads_jsonb` str/dict/None/garbage/
  non-dict-json, `_row_to_open_position` decode + null + missing-column, weather payload
  spread, end_date-wins-over-metadata, no-metadata-still-dispatches, paper INSERT source pins)
- 124 neighbor regression tests pass (test_exit_watcher + test_signal_scan_job)
- `ruff check` + `py_compile` clean on all 8 modified/new files
- Exit 4 (adaptive forecast-shift) now receives city + bucket bounds + entry mean
- Exit 3 (tp_48h / tp_48h_plus) + Exit 5 (near_expiry) continue working via `end_date`
  (resolution_at, wired in the prior weather-trade-rules lane); `end_date` from
  resolution_at deliberately wins over any stale metadata `end_date`
- Additive + idempotent: NULL default, non-weather INSERTs unchanged, missing-column read
  → None (no crash); malformed JSONB → None + logged (zero silent failure)

## 5. Known issues

- **Exit 2 (trailing stop) NOT yet activated.** It reads `high_water_price`, which is a
  runtime-tracked value (highest price seen since entry), not part of the scan-time
  metadata. Activating it needs a per-tick high-water updater that writes back to
  `positions.strategy_metadata['high_water_price']` whenever `current_price` sets a new
  high. That is a separate write-path lane (the registry is the only sanctioned position
  write surface) — recommended follow-up `WARP/weather-high-water-tracker`.
- Live execution path (`live_engine.execute`) does not persist `strategy_metadata` — weather
  is paper-only posture and the live path is guard-gated OFF, so this is intentionally out
  of scope.

## 6. What is next

- Operator: apply migration 076 to Supabase; set `WEATHER_STRATEGY_ENABLED=true` +
  `VISUALCROSSING_API_KEY` (new key) in Fly secrets to activate the weather strategy.
- Follow-up lane `WARP/weather-high-water-tracker` to activate Exit 2.

---

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: strategy_metadata persistence chain (TradeSignal → paper INSERT → registry read → exit payload) + weather Exit 4 activation
Not in Scope: Exit 2 high-water tracking (separate write-path lane), live-path metadata persistence, weather forecast/calibration internals
Suggested Next Step: WARP•SENTINEL validation (MAJOR tier — touches execution chain + new DB column) before merge
