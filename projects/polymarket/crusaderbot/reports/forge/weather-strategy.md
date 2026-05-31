# WARP•FORGE Report — weather-strategy

**Validation Tier:** STANDARD
**Claim Level:** FOUNDATION
**Validation Target:** WeatherStrategy module scaffold — locations, math, storage, calibration, forecast, market, strategy, scheduler registration
**Not in Scope:** Live CLOB execution, DB migrations, Telegram surface, position tracking across restarts, full end-to-end Polymarket weather market entry pipeline
**Suggested Next Step:** WARP🔹CMD review → set WEATHER_STRATEGY_ENABLED=true in .env for dry-run testing → confirm scan_cycle + monitor_cycle logs appear

---

## 1. What Was Built

New `strategies/weather/` module providing complete WeatherStrategy scaffold for CrusaderBot:

**locations.py** — 20 global cities across US (5), Europe (5), Asia (4), Oceania (1), South America (3), North America extras (2). Each entry carries ICAO METAR station code, lat/lon, and IANA timezone.

**math_utils.py** — Statistical core: `norm_cdf`, `bucket_prob` (probability mass in temperature bucket via normal CDF difference), `expected_value` (edge = p_true − price), `kelly_size` (fractional Kelly, alpha=0.25 LOCKED, MAX_BET=$20 cap).

**storage.py** — Async file-based JSON persistence. Market state serialized to `data/weather/markets/{market_id}.json`. Async wrappers (`load_market_state_async`, `save_market_state_async`) use `run_in_executor` to stay off the event loop for file I/O.

**calibration.py** — Self-learning sigma (forecast error std dev). Records per-resolved-market MAE; updates sigma after ≥30 samples via sigma ≈ MAE × √(π/2). Default 3.5°F until 30 samples. Clamped [1.0°F, 8.0°F]. Rolling 500-sample window.

**forecast.py** — Four async fetchers using `httpx`:
- `fetch_ecmwf`: Open-Meteo API, ECMWF IFS 0.4° model, daily Tmax/Tmin in °C → °F
- `fetch_hrrr`: Open-Meteo best_match (HRRR for CONUS), US-only guard
- `fetch_metar`: aviationweather.gov current observation — real-time cross-check
- `fetch_visual_crossing`: Visual Crossing Timeline API (gated on VISUALCROSSING_API_KEY env var; absent key → skipped with warning, not crash)
- `fetch_all`: concurrently gathers all sources; returns only available results
- `ensemble_tmax`: simple average of available Tmax forecasts

**market.py** — Gamma API async client. `fetch_weather_markets` queries active non-closed markets, filters by weather keywords, optionally by city. `_extract_bucket` parses bucket bounds from question text via regex (above/below/between/range patterns).

**strategy.py** — `WeatherStrategy` main class:
- `scan_cycle()` — hourly; bounced concurrency (sem=5); per-city: fetch markets + ensemble forecast → evaluate EV → emit candidates with price/p_true/ev/size metadata
- `monitor_cycle()` — 10-minute; checks open positions for stop-loss (−20%), TP (24h→hold / 24–48h→0.85 / 48h+→0.75), forecast-shift exit (|Δmean| ≥ 2°F)
- `get_status()` — returns dashboard summary (scan_count, open_positions, sigma, last_scan/monitor timestamps, cities_covered, candidates_last_scan)

**weather_config.json** — All parameters as JSON (min_ev=0.10, min_volume=500, max_spread=0.03, max_price=0.45, kelly_alpha=0.25, max_bet_usdc=20, stop_loss_pct=0.20, tp thresholds, forecast_exit_shift_f=2.0). No API keys.

**Scheduler integration (scheduler.py)** — Feature-flag gated: `if WEATHER_STRATEGY_ENABLED`: registers `weather_scan` (hourly interval) and `weather_monitor` (10-minute interval) jobs. Instance created once at scheduler setup; jobs share the same WeatherStrategy instance.

**Config (config.py)** — `WEATHER_STRATEGY_ENABLED: bool = False` added in the Heisenberg feature-flag block. `VISUALCROSSING_API_KEY` is NOT in config — read directly from `os.environ` in `forecast.py` per security requirement.

**Data directory** — `data/weather/markets/.gitkeep` + `data/weather/.gitkeep` committed to track the directory structure.

---

## 2. Current System Architecture

```
scheduler.setup_scheduler()
  └─ if WEATHER_STRATEGY_ENABLED
       ├─ WeatherStrategy.scan_cycle()   [hourly]
       │    ├─ fetch_weather_markets(city)   ← Gamma API
       │    ├─ fetch_all(loc, date)          ← ECMWF + HRRR + VisualCrossing
       │    ├─ bucket_prob(mean, sigma, low, high)
       │    ├─ expected_value(p_true, price)
       │    └─ kelly_size(ev, p_true, price, bankroll, alpha=0.25)
       └─ WeatherStrategy.monitor_cycle() [10 min]
            ├─ check stop-loss / TP / forecast-shift
            └─ close_position → storage update

strategies/weather/
  ├─ __init__.py        → WeatherStrategy
  ├─ locations.py       → 20 cities + ICAO codes
  ├─ math_utils.py      → norm_cdf, bucket_prob, ev, kelly_size
  ├─ storage.py         → file JSON r/w (data/weather/markets/)
  ├─ calibration.py     → MAE sigma (data/weather/calibration.json)
  ├─ forecast.py        → ECMWF/HRRR/METAR/VC httpx fetchers
  ├─ market.py          → Gamma API market fetch + bucket parser
  ├─ strategy.py        → WeatherStrategy class
  └─ weather_config.json → params (no API keys)

data/weather/
  ├─ calibration.json   [auto-created after first resolved market]
  └─ markets/           [per-market state JSON files]
```

No database migrations. No new dependencies (httpx already in pyproject.toml). VISUALCROSSING_API_KEY consumed from env only — never stored in config.

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/strategies/__init__.py`
- `projects/polymarket/crusaderbot/strategies/weather/__init__.py`
- `projects/polymarket/crusaderbot/strategies/weather/locations.py`
- `projects/polymarket/crusaderbot/strategies/weather/math_utils.py`
- `projects/polymarket/crusaderbot/strategies/weather/storage.py`
- `projects/polymarket/crusaderbot/strategies/weather/calibration.py`
- `projects/polymarket/crusaderbot/strategies/weather/forecast.py`
- `projects/polymarket/crusaderbot/strategies/weather/market.py`
- `projects/polymarket/crusaderbot/strategies/weather/strategy.py`
- `projects/polymarket/crusaderbot/strategies/weather/weather_config.json`
- `projects/polymarket/crusaderbot/data/weather/.gitkeep`
- `projects/polymarket/crusaderbot/data/weather/markets/.gitkeep`

**Modified:**
- `projects/polymarket/crusaderbot/config.py` — added `WEATHER_STRATEGY_ENABLED: bool = False`
- `projects/polymarket/crusaderbot/scheduler.py` — added `if WEATHER_STRATEGY_ENABLED` block registering `weather_scan` + `weather_monitor` jobs

---

## 4. What Is Working

- Import test passes: `from strategies.weather import WeatherStrategy; WeatherStrategy()` — no errors
- `get_status()` returns correct initial state (strategy=weather, enabled=True, cities_covered=20, sigma_f=3.5, all counters zero)
- All 8 module files import cleanly with proper cross-module dependencies
- Scheduler integration: jobs only register when `WEATHER_STRATEGY_ENABLED=true` — default OFF, no scheduler noise in paper-only deployments
- Security: `VISUALCROSSING_API_KEY` is ONLY read from `os.environ` at fetch time; absent key logs a warning and skips VC fetch cleanly; ECMWF + HRRR (free, no key) remain available
- Kelly: alpha=0.25 hardcoded in `kelly_size`, max_bet=$20, full Kelly (1.0) unreachable from config
- asyncio-only: all HTTP via httpx async; file I/O via `run_in_executor`; no threading
- `weather_config.json` contains zero secrets or API key values

---

## 5. Known Issues

- **FOUNDATION scope**: `scan_cycle` generates candidate dicts (market_id, ev, size) but does NOT automatically route them through the CrusaderBot risk gate + paper execution router. This is Phase 3 integration — candidates are currently logged only. Wire-up to `_process_candidate` / risk gate / router_execute is a separate lane requiring WARP🔹CMD directive.
- **Position state in-memory only**: `self._positions` is not persisted to DB or storage files; positions are reset on process restart. Acceptable at FOUNDATION level — persistence is Phase 3 work.
- **METAR data in monitor**: `fetch_metar` returns current observation temperature, not daily Tmax. For `monitor_cycle` forecast-shift exit checks, ECMWF/HRRR via `fetch_all` are used (METAR excluded from `fetch_all`). This is correct behavior.
- **Bucket parsing**: `_extract_bucket` in `market.py` uses simple regex; complex or multi-clause questions may return `(None, None)` — those markets are skipped at evaluation. Improvement lane when real market data is available.
- **HRRR coverage**: Open-Meteo `best_match` is used for HRRR (not the dedicated `hrrr_conus` model) because HRRR is geographic. Works for CONUS cities; returns US-climate-model data for non-CONUS (acceptable for ensemble averaging).

---

## 6. What Is Next

1. **WARP🔹CMD dry-run**: Set `WEATHER_STRATEGY_ENABLED=true` + `VISUALCROSSING_API_KEY=<new_key>` in local `.env`; run `scan_cycle()` manually to confirm candidates appear in logs
2. **Phase 3 integration (separate lane)**: Wire `scan_cycle` candidates through the existing risk gate + paper execution router (`domain/risk/gate` + `domain/execution/router`)
3. **Position persistence (separate lane)**: Persist `self._positions` to DB (new table or leverage existing `positions` table with `strategy_type='weather'`)
4. **Calibration feedback loop (separate lane)**: Wire `calibration.update_sigma` after market resolution via the existing `check_resolutions` / redeem pipeline
5. **Security action (OPERATOR)**: Revoke the old `vc_key` from `Polybot_Weather/config.json` at Visual Crossing dashboard; generate a fresh key; store as `VISUALCROSSING_API_KEY` in Fly secrets
