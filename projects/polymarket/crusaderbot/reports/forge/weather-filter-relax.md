# WARP•FORGE Report — weather-filter-relax

## 1. What was built

Relaxed the Weather Monitor entry filter thresholds in `weather_config.json` to allow more trades while preserving signal quality. The previous config was too restrictive (10% EV requirement, $500 volume floor, 3% max spread, 45¢ price ceiling), resulting in zero trades since strategy activation despite the scanner running every hour across 20 cities.

## 2. Current system architecture

No architecture change. `WeatherStrategy._load_config()` reads `weather_config.json` at the start of every `scan_cycle()`, so changes take effect on the next scan without restart or redeploy.

Entry filter chain (all must pass):
1. Volume 24h ≥ `min_volume`
2. Spread ≤ `max_spread`
3. YES price ≤ `max_price`
4. Bucket defined (low/high)
5. EV ≥ `min_ev` ← most selective gate

Sizing: fractional Kelly α=0.25 (locked), max `max_bet_usdc` per trade. Exit rules unchanged.

## 3. Files created / modified

| Action | Path |
|--------|------|
| Modified | `projects/polymarket/crusaderbot/strategies/weather/weather_config.json` |

## 4. What is working

| Parameter | Before | After | Reason |
|-----------|--------|-------|--------|
| `min_ev` | 0.10 (10%) | 0.04 (4%) | 10% edge almost never exists in efficiently-priced weather markets; 4% is meaningful but achievable |
| `min_volume` | 500.0 | 200.0 | Lower liquidity floor — smaller markets still worth trading at $20 max bet |
| `max_spread` | 0.03 (3%) | 0.05 (5%) | Slightly wider spread tolerance without significant fill-quality degradation |
| `max_price` | 0.45 | 0.65 | Covers significantly more of the market probability range; was cutting 55%+ of valid markets |

Unchanged: `kelly_alpha=0.25`, `max_bet_usdc=20.0`, `stop_loss_pct=0.20`, all TP rules, `forecast_exit_shift_f=2.0`.

## 5. Known issues

- `min_ev=0.04` may produce more marginal entries; paper observation required to calibrate whether 4% is the right floor or needs further tuning.
- `max_price=0.65` lets in markets priced 45–65¢ which are closer to the efficient mid-range. The ensemble forecast edge still acts as the primary quality gate.

## 6. What is next

- Monitor paper trades from weather_monitor over next 24–48h — watch Telegram for `weather_signal_fired` alerts.
- If trade frequency remains zero, investigate whether Visual Crossing API key is active (only ECMWF + HRRR without it).
- If trade frequency is too high (>3/day), raise `min_ev` back toward 0.06.

---

**Validation Tier:** MINOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** `strategies/weather/weather_config.json` entry thresholds only — no runtime code change
**Not in Scope:** exit rules, Kelly fraction, max bet size, forecast sources, scan scheduling
**Suggested Next Step:** WARP🔹CMD review — config-only change, no code modified
