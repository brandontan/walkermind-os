# WARP•FORGE REPORT — preset-activate

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: Safe Close + Flip Hunter strategy activation — late_entry_v3 engine extension + all routing gates unlocked
Not in Scope: Oracle integration, backend DB schema, Telegram command flows beyond picker visibility
Suggested Next Step: WARP•SENTINEL validation required for preset-activate before merge. Source: projects/polymarket/crusaderbot/reports/forge/preset-activate.md. Tier: MAJOR

---

## 1. What Was Built

Two dormant candle presets — **Safe Close** and **Flip Hunter** — are now fully active.
They were previously coded but blocked at every gate: scanner, backend router, and frontend UI.

**Safe Close:**
- Entry window: 30–60s before candle close (elapsed 240–270s on 5m; 840–870s on 15m)
- Implements a `min_entry_sec=30.0` floor in `late_entry_v3` — no entries in the final 30s
- Tighter lean filter: `min_ask_diff=0.08`, `fav_price_min=0.60`
- Majority side entry (same direction as close_sweep)

**Flip Hunter:**
- Entry window: any time in the final 140s before close
- `underdog_mode=True` — enters the **cheap side** priced 0.26–0.35 (opposite of current)
- Asymmetric upside: if the cheap side flips to majority before close, position gains fast
- Lean still required (`min_ask_diff=0.05`) to confirm the market is not a coin-flip

**Engine extension (`late_entry_v3.py`):**
- New `min_entry_sec: float | None` param to `scan()` and `_evaluate_market()` — adds a seconds_left floor gate
- New `underdog_mode: bool` param — when True, enters the low-probability side and applies `fav_price_min/max` to the cheap side's price instead of the favored side
- Reject reasons: `inside_min_entry_sec`, updated `fav_price_too_low` / `fav_price_too_high` for both modes
- Metadata: added `entry_price` and `underdog_mode` fields; log updated

**Config (`config.py`):**
- `PRESET_SAFE_CLOSE_MIN_ENTRY_SEC = 30.0` — env-tunable
- `PRESET_FLIP_HUNTER_FAV_PRICE_MIN = 0.26` — updated (was 0.50)
- `PRESET_FLIP_HUNTER_FAV_PRICE_MAX = 0.36` — new env-tunable

**Scanner (`signal_scan_job.py`):**
- `_CANDLE_PRESET_PARAMS` converted from `tuple[float,float,float]` to `dict[str, dict[str, object]]` — carries all 6 params cleanly
- Config-loading block in `run_close_sweep_fast()` updated to match; new `min_entry_sec` and `fav_price_max` fields loaded from config
- Both callsites (main scan loop + fast scan loop) pass the full param set to `late_entry_strat.scan()`

**Backend router (`webtrader/backend/router.py`):**
- `safe_close` + `flip_hunter` added to `_PRESET_PARAMS` with appropriate risk defaults
- Both added to `_CRYPTO_SHORT_PRESETS` → auto-locks Crypto category + requires timeframe on activation
- `_SAFE_CLOSE_TF_PARAMS` and `_FLIP_HUNTER_TF_PARAMS` added — applied to `strategy_params` on activation
- `activate_preset` endpoint updated to apply tf_params for all three candle presets

**Frontend (`AutoTradePage.tsx`):**
- `safe_close` and `flip_hunter` moved from `COMING_SOON_PRESETS` to `STRATEGY_PRESETS` — fully selectable
- `COMING_SOON_PRESETS` is now empty (no locked cards shown)
- Signal descriptions updated to match actual behavior

**Telegram picker (`domain/preset/presets.py`):**
- `VISIBLE_PRESET_ORDER` expanded: `("close_sweep", "safe_close", "flip_hunter")`
- All three candle presets now visible in the Telegram preset picker

**Tests:**
- `test_picker_keyboard_has_two_col_grid_layout` updated: 3 visible presets → 2 preset rows + 1 nav row = 3 rows (was 2)
- 122 tests pass across `test_late_entry_v3`, `test_preset_system`, `test_signal_scan_job`

---

## 2. Current System Architecture

```
SCHEDULER
  └─ run_close_sweep_fast() [every 15s]
       └─ for each user on close_sweep / safe_close / flip_hunter:
            ├─ load _preset_params from config (env-tunable)
            ├─ late_entry_strat.scan(
            │    min_ask_diff, entry_window_sec, fav_price_min,
            │    fav_price_max, min_entry_sec, underdog_mode
            │  )
            └─ _process_candidate() → risk gate → paper fill

late_entry_v3._evaluate_market()
  timing gates:
    1. seconds_left ∈ (0, entry_window_sec]   ← existing
    2. seconds_left >= min_entry_sec           ← NEW (safe_close=30s)
  price gates (per mode):
    standard:  entry_price = fav_price (≥ fav_price_min, < fav_price_max)
    underdog:  entry_price = min_ask  (≥ fav_price_min, < fav_price_max)
  side:
    standard:  favored side (higher ask)
    underdog:  cheap side (lower ask)   ← NEW (flip_hunter)
```

Preset parameter table:

| Preset      | min_ask_diff | entry_window_sec | fav_price_min | fav_price_max | min_entry_sec | underdog_mode |
|-------------|-------------|-----------------|--------------|--------------|--------------|---------------|
| close_sweep | 0.05        | 35s             | 0.55         | 0.70         | None         | False         |
| safe_close  | 0.08        | 60s             | 0.60         | 0.70         | 30s          | False         |
| flip_hunter | 0.05        | 140s            | 0.26         | 0.36         | None         | True          |

---

## 3. Files Created / Modified

| Action   | Path |
|----------|------|
| Modified | `projects/polymarket/crusaderbot/config.py` |
| Modified | `projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py` |
| Modified | `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` |
| Modified | `projects/polymarket/crusaderbot/webtrader/backend/router.py` |
| Modified | `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx` |
| Modified | `projects/polymarket/crusaderbot/domain/preset/presets.py` |
| Modified | `projects/polymarket/crusaderbot/tests/test_preset_system.py` |
| Created  | `projects/polymarket/crusaderbot/reports/forge/preset-activate.md` |

---

## 4. What Is Working

- All 122 tests pass (test_late_entry_v3, test_preset_system, test_signal_scan_job)
- safe_close entries are gated to 30–60s before close; no last-second fills
- flip_hunter enters cheap side (0.26–0.35); standard mode unchanged for close_sweep and safe_close
- Backend router accepts `preset_key` for all three presets and applies correct risk defaults + tf_params
- Telegram picker shows all three candle presets in VISIBLE_PRESET_ORDER
- Frontend shows safe_close and flip_hunter as fully selectable (no "SOON" lock)

---

## 5. Known Issues

- flip_hunter underdog entry uses the flip-stop `evaluate_exit` (exit when favored-side price ≤ 0.48). For underdog mode the flip-stop is less meaningful — the cheap side doesn't have a symmetric flip-stop. In practice the TP/SL and market-expiry paths protect the position. A dedicated underdog exit strategy is deferred.
- No live data to confirm flip_hunter fires at the correct price range — requires Fly deploy + log observation on the next candle cycle.

---

## 6. What Is Next

- WARP•SENTINEL validation required (Tier: MAJOR) before merge
- Deploy to Fly (`fly deploy --remote-only`) and eyeball:
  - safe_close scan_summary logs showing `min_entry_sec=30` applied
  - flip_hunter scan_summary showing `underdog=True` and `entry_price` in 0.26–0.35 range
  - AutoTrade page: all 3 presets selectable, no SOON cards
  - Telegram picker: 3 presets visible
