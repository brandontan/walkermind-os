# WARP•FORGE Report — candle-preset-asset-config

## 1. What Was Built

Trimmed the crypto-asset universe for the three candle presets (Close Sweep, Safe Close, Flip Hunter) and updated the default-active selection across frontend and backend.

Changes:
- **Removed**: XRP, DOGE, HYPE — eliminated entirely from the asset selector and backend validation list.
- **Kept as available (opt-in)**: SOL, BNB — present in the picker but not selected by default.
- **Default-active**: BTC + ETH — selected on every fresh preset activation.
- **Signal description**: Close Sweep label updated from "BTC/ETH/SOL" → "BTC/ETH/SOL/BNB" to accurately reflect the available universe.
- **Timeframes**: unchanged — 5M and 15M both kept.

## 2. Current System Architecture

No architectural change. The existing asset-filtering flow remains:

```
AutoTradePage (selectedAssets state)
  → api.activatePreset(key, tf, assets)
  → POST /api/web/autotrade/activate
  → router.py: _VALID_ASSETS filter → strip invalid assets
  → user_settings.selected_assets (JSONB array)
  → signal_scan_job: get_crypto_window_markets(timeframe, selected_assets)
```

`_VALID_ASSETS` is derived from `_CRYPTO_SHORT_ASSETS` so the backend rejects any removed ticker even if a client sends it (e.g. an old browser session with XRP still selected).

## 3. Files Created / Modified

| File | Change |
|---|---|
| `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx` | `CRYPTO_ASSETS` 7→4 items; `CRYPTO_ASSETS_DEFAULT` `["BTC"]`→`["BTC","ETH"]`; comment updated; Close Sweep signal text updated |
| `projects/polymarket/crusaderbot/webtrader/backend/router.py` | `_CRYPTO_SHORT_ASSETS` 7→4; `_DEFAULT_CRYPTO_SHORT_ASSETS` `("BTC",)`→`("BTC","ETH")`; comment updated |

## 4. What Is Working

- Asset picker renders BTC / ETH / SOL / BNB only (4-button row).
- Fresh preset activation defaults BTC + ETH pre-selected; SOL / BNB available opt-in.
- Backend `_VALID_ASSETS` derived from `_CRYPTO_SHORT_ASSETS` — XRP/DOGE/HYPE rejected server-side even from stale clients.
- `_DEFAULT_CRYPTO_SHORT_ASSETS` used when `body.selected_assets` is empty → activating with no explicit selection now defaults to `["BTC", "ETH"]`.
- 2000 Python tests pass; py_compile clean on both modified files.
- Frontend: constant updates are type-safe (readonly tuple narrowed from 7 to 4 string literals).

## 5. Known Issues

None. This is a constant-update lane — no runtime logic changed.

## 6. What Is Next

WARP🔹CMD review + Fly.io redeploy (frontend static rebuild ships the trimmed asset picker to prod).

---

**Validation Tier**: MINOR
**Claim Level**: NARROW INTEGRATION
**Validation Target**: asset selector constants (frontend + backend)
**Not in Scope**: signal_scan_job market filtering logic, strategy params, risk gate, timeframe handling
**Suggested Next Step**: WARP🔹CMD review + merge + Fly.io redeploy
