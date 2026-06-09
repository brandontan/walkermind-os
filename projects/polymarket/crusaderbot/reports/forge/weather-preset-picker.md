# WARP•FORGE — weather-preset-picker

Validation Tier: MINOR
Claim Level: NARROW INTEGRATION
Validation Target: WebTrader AutoTrade preset picker surfaces `weather_monitor`.
Not in Scope: weather scan/exit logic, backend routing, Telegram picker, Fly secrets.
Suggested Next Step: WARP🔹CMD review → merge → CD auto-deploy.

## 1. What was built

Added the `weather_monitor` entry to the hardcoded `STRATEGY_PRESETS` array in the
WebTrader frontend so it renders as a selectable card in the AutoTrade preset picker.

The WARP-49 pipeline PR (#1518) wired `weather_monitor` into every backend/domain
layer (`_PRESET_TO_STRATEGY`, `_PRESET_PARAMS`, `_ADMIN_STRATEGIES`,
`bot/presets.py`, `domain/preset/presets.py`) and the DB `strategies` row, but the
React picker keeps its own hardcoded preset list. With the strategy globally enabled
in the admin console, the preset still did not appear to users because the frontend
array was never extended. This adds the missing card.

## 2. Current system architecture

Picker render path (unchanged):
`STRATEGY_PRESETS` (frontend constant) → filtered by `presetEnabled[key] !== false`
(fed from `/autotrade/preset-availability`) → card grid. `weather_monitor` is NOT in
`CRYPTO_SHORT_PRESETS`, so it renders without the timeframe/asset sub-config and
activates via the existing non-crypto branch `api.activatePreset(key)`.

## 3. Files created / modified

- Modified: `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx`
- Created:  `projects/polymarket/crusaderbot/reports/forge/weather-preset-picker.md`

## 4. What is working

- `tsc --noEmit` clean.
- `npm run build` (tsc + vite) succeeds.
- New card mirrors the domain `Preset` definition (emoji 🌤, name "Weather Monitor",
  balanced badge, description verbatim from `domain/preset/presets.py`).
- `balanced` risk maps to an existing `riskColor` entry; 4th card wraps cleanly in
  the `md:grid-cols-3` layout.

## 5. Known issues

- `engine: "W.A.R.P_FORECAST"` is a frontend display label (no canonical engine name
  exists in the codebase; crypto presets use `W.A.R.P_STRIKE`). Descriptive only.
- Weather still does not place trades until `WEATHER_STRATEGY_ENABLED=true` is set in
  Fly secrets — that gate is independent of picker visibility.

## 6. What is next

- Set `WEATHER_STRATEGY_ENABLED=true` (and optionally `VISUALCROSSING_API_KEY`) in Fly.
