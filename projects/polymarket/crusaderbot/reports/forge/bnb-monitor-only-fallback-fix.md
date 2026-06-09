# WARP•ROOT — bnb-monitor-only-fallback-fix

Role: WARP•R00T
Branch: WARP/ROOT/bnb-monitor-only-fallback-fix
Date: 2026-05-31 Asia/Jakarta
Validation Tier: MAJOR (asset-eligibility on the candle trade path)
Claim Level: NARROW INTEGRATION
Validation Target: `get_crypto_window_markets` default-asset resolution (integrations/polymarket.py)
Not in Scope: re-enabling BNB (owner/edge-stats decision); the `domain/strategy/eligibility.py` `assets=None` whitelist match (no longer reachable with BNB once the fetch excludes it)
Closes: WARP/ROOT/prelaunch-system-audit finding F3 (LIVE-blocker B2)

## 1. What was built

Closed the BNB monitor-only bypass. `get_crypto_window_markets(tf, None)` previously defaulted its coin list to `["btc","eth","sol","bnb"]` (integrations/polymarket.py:220). A user whose `selected_assets` was empty — or BNB-only, which `_filter_monitor_only_assets` strips to empty → `assets=None` — therefore re-introduced BNB candle markets directly into the trade path (upserted, eligibility-matched with `assets=None`, gated, executed). Paper-contained today, but would route real BNB orders the instant the LIVE guards flip. The coin resolution is now a pure helper `_resolve_tradeable_coins(assets)` that (a) defaults to the tradeable set BTC/ETH/SOL and (b) **always** excludes monitor-only coins (BNB) — even from an explicit `assets` list — so a non-tradeable candle window can never be fetched.

## 2. Current system architecture

No architectural change. `get_crypto_window_markets` keeps the same signature and slug-fetch flow; only the coin-list derivation changed (inline default → `_resolve_tradeable_coins`). New module constants `_DEFAULT_TRADEABLE_COINS=("btc","eth","sol")` and `_MONITOR_ONLY_COINS=frozenset({"bnb"})` mirror `services/signal_scan/signal_scan_job._MONITOR_ONLY_ASSETS` (lowercased for slug use; comment cross-references it for sync). If resolution yields no coins (e.g. a direct BNB-only call), the function returns `[]` (fetch nothing) rather than substituting. The monitor-only *observation* path (30-day edge stats via `market_data`/`ASSET_ALIASES`) is untouched.

## 3. Files created / modified

- Modified: `projects/polymarket/crusaderbot/integrations/polymarket.py` (new `_DEFAULT_TRADEABLE_COINS` + `_MONITOR_ONLY_COINS` + `_resolve_tradeable_coins`; `get_crypto_window_markets` uses it + early-return on empty; docstring).
- Modified: `projects/polymarket/crusaderbot/tests/test_bnb_monitor_only.py` (+4 tests: defaults exclude BNB, explicit-list strip, case/blank normalisation, integration pin).
- Modified (state): `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `projects/polymarket/crusaderbot/state/CHANGELOG.md`.

## 4. What is working

`_resolve_tradeable_coins(None) == ["btc","eth","sol"]` (no BNB); `["BTC","BNB"] → ["btc"]`; `["bnb"] → []`; case/blank normalised. `get_crypto_window_markets` routes through the resolver (integration pin). `ruff` + `py_compile` clean. test_bnb_monitor_only.py + test_candle_sync_observability.py **28/28 pass** (the observability tests exercise the real function with explicit assets, confirming the tradeable path is intact); test_late_entry_v3.py **51/51 pass** (engine unaffected).

## 5. Known issues

- `_MONITOR_ONLY_COINS` here duplicates `services/signal_scan/signal_scan_job._MONITOR_ONLY_ASSETS` (lowercased). Documented + comment-linked; a future cleanup could hoist a single canonical tradeable-asset constant to a shared module (low priority — both are small frozensets with a sync note).
- XRP/DOGE/HYPE remain non-tradeable as before (absent from the default + rejected at persistence); they were never in `_MONITOR_ONLY_*`, so they are simply not in the tradeable default.

## 6. What is next

WARP•SENTINEL validation (MAJOR — asset-eligibility on the trade path). Then WARP🔹CMD merge decision. Closes audit F3 / LIVE-readiness B2. Remaining authorized lanes: `blueprint-rbac-roster-sync`, `dead-code-archive`.

Suggested Next Step: WARP•SENTINEL pass; proceed to the docs/cleanup lanes.
