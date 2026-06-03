# WARP•FORGE — webtrader-feed-preset-aware

Role: WARP•FORGE — fixing an owner-reported bug: the dashboard scanner showed
crypto markets/signals while the weather preset was active.
Validation Tier: **STANDARD** (WebTrader feed + an additive, fail-soft market-table
sync; no risk / execution / capital / gate / candidate-flow change)
Claim Level: **NARROW INTEGRATION**
Validation Target: `/market-feed` now reflects the user's active-preset category,
and weather markets are persisted so the feed is populated on the weather preset.
Not in Scope: trading logic, risk gate, execution, activation guards, the scanner's
candidate emission (unchanged); the signal carousel (already preset-correct via
`/signals/recent`); DB migrations (none).
Suggested Next Step: WARP🔹CMD review/merge + Fly.io redeploy (the weather-market
sync only runs in the deployed scan loop). Linear WARP-52.

---

## 1. What was built

Owner report: "Scanner masih tampilkan market dan signal crypto saat gw set
strategy weather." Root cause: `/market-feed` was **hardcoded to crypto** up/down
candle markets (`slug LIKE '%updown%'`, assets btc/eth/sol…) and ignored the active
preset entirely — so on `weather_monitor` the scanner panel's MARKETS rows (and the
terminal "markets" line, both fed by this endpoint) still showed BTC/ETH.

Two parts:

- **Preset-aware feed (`webtrader/backend/router.py`)** — `get_market_feed` now reads
  the user's `active_preset` (from `user_settings`), maps it to a category via the
  existing `_PRESET_LOCKED_CATEGORY`, and dispatches:
  - **Crypto** (or no/unknown preset → FAIL-SAFE default) → the original up/down
    candle query, unchanged.
  - **Weather** → `_weather_market_feed`: nearest-resolution `category='Weather'`
    markets, one row per city (deduped via `_weather_asset_code`, which matches the
    `LOCATIONS` roster → compact codes NYC/LA/CHI…). No liquidity floor (Gamma weather
    books are thin).
  - **Other (e.g. Sports)** → `_category_market_feed`: nearest in-category markets
    (`category ILIKE`), generic slug-derived label.
- **Weather markets now persisted (`services/signal_scan/signal_scan_job.py`)** —
  the missing half: unlike crypto/sports (which upsert into the `markets` table via
  `_upsert_crypto_window_markets` / `_upsert_sports_markets`), weather markets were
  fetched live from Gamma during the scan and **never written to the DB**, so a
  category-filtered feed query would return empty. Added `_upsert_weather_markets`
  (mirror of `_upsert_sports_markets`, `category='Weather'`, idempotent, fail-soft)
  + `_sync_weather_markets` (one Gamma call: `fetch_weather_markets(limit=200)` =
  all weather markets), called once per scan before the user loop, gated on
  `WEATHER_STRATEGY_ENABLED` via the runtime-config overlay — exactly mirroring the
  playbook `_sync_playbook_sports_markets` precedent. This also lets weather
  candidates resolve in `_load_market` (same benefit the sports sync gave PLAYBOOK).

No frontend change: `ScannerPanel` already renders whatever `marketFeed` contains,
so the panel + the top `MarketFeed` strip now both follow the active strategy.

## 2. Current system architecture

No architectural change. The scan pipeline (strategy scan → candidate → risk gate →
execution) is untouched; the new sync is an additive, gated, fail-soft market-table
upsert running alongside the existing crypto/sports syncs. The feed endpoint is pure
read. The signal carousel was already preset-correct (it reads the user's own
`/signals/recent`, which only contains weather signals when the weather scan emitted
them).

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — preset-aware
  `get_market_feed` + `_crypto/_weather/_category_market_feed` + `_weather_asset_code`
  + `_lean_from_prob` + `_WX_CITY_CODE`
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` —
  `_upsert_weather_markets` + `_sync_weather_markets` + gated pre-loop call
- `projects/polymarket/crusaderbot/tests/test_market_feed_preset.py` — NEW (10 tests)
- `projects/polymarket/crusaderbot/tests/test_signal_scan_job.py` — +3 weather tests
- `projects/polymarket/crusaderbot/reports/forge/webtrader-feed-preset-aware.md` — this report
- State: `state/PROJECT_STATE.md` + `state/CHANGELOG.md`

## 4. What is working

- **13 new hermetic tests pass** (3 weather upsert/sync in `test_signal_scan_job.py`
  + 10 feed-dispatch/helper in `test_market_feed_preset.py`); 92 tests in the two
  scan/feed files pass; 25 bnb-monitor regression tests pass.
- `ruff check` clean on all changed files; `py_compile` clean.
- Dispatch verified: weather preset → `category='Weather'` query, never the crypto
  `updown` query; crypto/none → `updown`; sports → `category ILIKE`. City dedup
  verified (two NYC buckets → one NYC row).
- `_weather_asset_code` matches the `LOCATIONS` roster (NYC/LA/CHI…), falls back to
  `WX` for non-weather text.
- Fail-soft preserved: a Gamma fetch failure logs + returns 0 (no scan disruption);
  per-market upsert errors are caught; the feed default is Crypto (FAIL-SAFE) when
  the preset is unknown.

## 5. Known issues

- The weather feed is **populated only after the deployed scan runs at least once**
  with `WEATHER_STRATEGY_ENABLED` on (it writes the rows). On a fresh DB before the
  first weather scan tick the MARKETS section is briefly empty (correct — never shows
  crypto). Verified by logic + tests, not against live Gamma data in this sandbox.
- `_weather_asset_code` covers the 24-city `LOCATIONS` roster; a brand-new city
  Polymarket adds before `LOCATIONS` is updated falls back to `WX` (cosmetic).
- The generic `_category_market_feed` label/asset is slug-derived (best-effort) — fine
  for Sports; not as polished as the crypto/weather branches.

## 6. What is next

- WARP🔹CMD review/merge + Fly.io redeploy (the sync runs in the deployed worker).
- Optional: extend `_weather_asset_code` codes as the `LOCATIONS` roster grows;
  polish the generic category feed labels when PLAYBOOK web UX is worked.

---

- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target: preset-aware /market-feed + weather-market persistence
- Not in Scope: risk/execution/guards, candidate flow, signal carousel, migrations
- Suggested Next Step: WARP🔹CMD review/merge + redeploy
