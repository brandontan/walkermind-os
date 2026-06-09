# WARP•FORGE — weather-category-lock

## 1. What was built

Auto-lock market category filter when a preset is activated. Activating
`weather_monitor` forces the market filter to **Weather** only.
Activating any crypto-short preset (`close_sweep`, `safe_close`,
`flip_hunter`) forces it to **Crypto** only. Presets not in the map leave
category_filters untouched.

Replaces the old `isCryptoShortActive` boolean with a generalised
`PRESET_LOCKED_CATEGORY` mapping shared by both backend and frontend.

## 2. Current system architecture

```
activate_preset (POST /trading/preset)
  └─ _PRESET_LOCKED_CATEGORY dict  →  category_filters=[locked]
        │
        └─ COALESCE(category_filters) in SQL upsert
               └─ signal_scan_job reads category_filters per user
                      └─ filters markets before scan
```

Frontend mirrors the map as `PRESET_LOCKED_CATEGORY` constant:
- Category checkboxes are `disabled` and show "Locked to X" badge
  when `lockedCategory` is set.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/webtrader/backend/router.py`
  — added `_PRESET_LOCKED_CATEGORY` dict (after `_CRYPTO_SHORT_PRESETS`)
  — `activate_preset()`: replaces `category_filters = ["Crypto"] if is_crypto_short else None`
    with `_locked_category = _PRESET_LOCKED_CATEGORY.get(body.preset_key)`
  — `is_crypto_short` retained (still governs timeframe / assets logic)

- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx`
  — added `PRESET_LOCKED_CATEGORY: Record<string, string>` constant
  — removed stale `isCryptoShortActive` declaration (TS6133 unused var)
  — market filter section uses `lockedCategory` derived from `PRESET_LOCKED_CATEGORY[state.active_preset]`

- `projects/polymarket/crusaderbot/reports/forge/weather-category-lock.md` (this file)

## 4. What is working

- `tsc --noEmit` passes clean (zero errors)
- `ruff check router.py` passes clean
- Activating `weather_monitor` → `category_filters=["Weather"]` in DB + UI
- Activating crypto-short presets → `category_filters=["Crypto"]` (unchanged behaviour)
- Non-mapped presets → `category_filters` left untouched (COALESCE NULL)

## 5. Known issues

None.

## 6. What is next

WARP-49 trade rules: EV formula correction, entry filters (MIN_HOURS=2,
MAX_HOURS=72, MIN_SIZE≥$0.50), trailing stop logic, forecast-change exit
upgrade, multi-user shared forecast cache.

---

Validation Tier: MINOR
Claim Level: NARROW INTEGRATION
Validation Target: activate_preset() category_filters path + frontend preset lock UI
Not in Scope: signal_scan_job category filtering, exit logic, trade rules
Suggested Next Step: WARP🔹CMD review → merge
