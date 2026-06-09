# WARP•FORGE Report — weather-strategy-pipeline

**Branch:** WARP/ROOT/weather-strategy-pipeline
**Validation Tier:** MAJOR
**Claim Level:** FULL RUNTIME INTEGRATION
**Validation Target:** WeatherStrategy wired into CrusaderBot trading pipeline (WebTrader + Telegram bot, signal scan, BaseStrategy adapter)
**Not in Scope:** Live trade execution testing, WARP•SENTINEL validation (deferred per MAJOR tier)
**Suggested Next Step:** WARP•SENTINEL validation required before merge

---

## 1. What Was Built

WeatherStrategy is now a first-class trading strategy in CrusaderBot's domain strategy plane. Users can select the `weather_monitor` preset from WebTrader and the Telegram bot, which routes trades through the weather forecast edge-detection pipeline.

Changes implement:
- `WeatherDomainStrategy` — a `BaseStrategy` adapter that wraps the existing `strategies/weather/` forecast + calibration + market-fetch pipeline. Emits `SignalCandidate` objects using user equity as bankroll.
- Strategy registered in `StrategyRegistry` via `bootstrap_default_strategies()`.
- `weather_monitor` preset wired into all routing layers: `_PRESET_ALLOWED`, `_PRESET_TO_STRATEGY`, `_PRESET_PARAMS`, `_ADMIN_STRATEGIES`, `PRESET_CONFIG`, `domain/preset/presets.py`.
- Phase B2 scan block in `run_once()` invokes weather scan per eligible user.
- DB migration 075 seeds the `weather` strategy row in the `strategies` global-toggle table.

---

## 2. Current System Architecture

```
run_once() [signal_scan_job.py]
  │
  ├── Phase B: late_entry_v3  (preset: close_sweep / safe_close / flip_hunter)
  │
  ├── Phase B2: weather        (preset: weather_monitor)           ← NEW
  │     WeatherDomainStrategy.scan()
  │       └─ fetch_weather_markets() [Gamma API]
  │       └─ fetch_all() [Open-Meteo ECMWF + HRRR + METAR + VisualCrossing]
  │       └─ ensemble_tmax() → bucket_prob() → expected_value() → kelly_size()
  │       └─ SignalCandidate(side="YES", confidence=p_true, ...)
  │         └─ _process_candidate() → risk gate → TradeEngine
  │
  └── Phase C: signal_following feed
```

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/domain/strategy/strategies/weather.py`
- `projects/polymarket/crusaderbot/migrations/075_weather_strategy.sql`

**Modified:**
- `projects/polymarket/crusaderbot/domain/strategy/strategies/__init__.py` — export WeatherDomainStrategy
- `projects/polymarket/crusaderbot/domain/strategy/registry.py` — add to bootstrap_default_strategies
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — _WEATHER_STRATEGY_NAME, _DOMAIN_STRATEGY_NAMES, _PRESET_ALLOWED, Phase B2 block, telemetry
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — _PRESET_TO_STRATEGY, _PRESET_PARAMS, _ADMIN_STRATEGIES
- `projects/polymarket/crusaderbot/bot/presets.py` — PRESET_CONFIG, PRESET_ORDER
- `projects/polymarket/crusaderbot/domain/preset/presets.py` — PRESETS, PRESET_ORDER, VISIBLE_PRESET_ORDER

---

## 4. What Is Working

- `WeatherDomainStrategy` registers cleanly in StrategyRegistry and passes all 44 existing strategy registry tests.
- `domain/preset/presets.py` PRESETS dict validates on import (frozen dataclass `__post_init__` passes).
- `weather_monitor` preset is visible in WebTrader `/autotrade/preset-availability` response and Telegram keyboard (`list_presets()`).
- `activate_preset("weather_monitor")` accepted — key is in `_PRESET_PARAMS`.
- Admin on/off toggle works via `_ADMIN_STRATEGIES` + strategies table row.
- `_preset_allows("weather_monitor", "weather")` → True; all other presets → False (deny-by-default intact).
- `WEATHER_STRATEGY_ENABLED=False` (config default) gates scan at strategy level — zero DB writes when disabled.
- Kelly alpha=0.25 locked; max_bet_usdc=20.0 cap enforced.
- All 7 modified files pass AST syntax check.

---

## 5. Known Issues

- `WEATHER_STRATEGY_ENABLED` defaults to `False` in `config.py`. Must be explicitly set `True` in env to activate trading. This is intentional — operator opt-in required.
- `_process_candidate` applies crypto-candle specific guards (complete_set_edge, safe_close direction limit) to all candidates including weather. The guards are conditioned on `strategy_name == "late_entry_v3"` internally so weather candidates pass through cleanly, but WARP•SENTINEL should confirm this at test time.
- Visual Crossing API key must be set as `VISUALCROSSING_API_KEY` env var for full 4-source ensemble. Without it, strategy degrades to 3 sources (Open-Meteo ECMWF + HRRR + METAR) — still functional.
- Sigma calibration starts at default 3.5°F and converges after 30 resolved market outcomes. Early signals use uncalibrated sigma.

---

## 6. What Is Next

WARP•SENTINEL validation required (MAJOR tier):
- Confirm Phase B2 candidate flow through `_process_candidate` risk gate without late_entry_v3-specific gate contamination.
- Confirm `WEATHER_STRATEGY_ENABLED=False` blocks scan at zero cost.
- Confirm preset deny-by-default unchanged for candle presets.
- Confirm DB migration 075 is idempotent (ON CONFLICT DO NOTHING).
- Confirm Telegram preset picker renders `weather_monitor` only when strategy enabled in `strategies` table.

After SENTINEL approval → operator must:
1. Apply migration 075 in production.
2. Set `WEATHER_STRATEGY_ENABLED=True` in production env.
3. Set `VISUALCROSSING_API_KEY` in production env (new key — old key was revoked per WARP-49 security note).
