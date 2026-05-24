# WARP•FORGE Report — crypto-short-asset-selector

Branch: WARP/crypto-short-asset-selector
Validation Tier: MAJOR (scan pipeline + market fetch + strategy gating)
Claim Level: NARROW INTEGRATION (code + unit/typecheck/build + live Gamma probe;
full trade proof needs Fly deploy + migration 050 applied + a live candle window)
Validation Target: inline asset+timeframe selector for crypto-short presets,
asset filtering, and a fetch-coverage fix so the scanner actually sees the live
5m/15m crypto candle markets.
Not in Scope: assets beyond BTC/ETH/SOL/BNB in the UI; CLOB-orderbook depth as a
liquidity source (Gamma `liquidity` is populated once a candle enters its window,
verified live — so it is sufficient).
Suggested Next Step: apply migration 050, Fly redeploy, re-test Close Sweep/Crypto
Scalper @ 5m → expect `markets_eligible > 0` and BTC/ETH/SOL candle positions.

## 1. What was built

1. **Inline strategy config** — selecting Close Sweep or Crypto Scalper expands
   the strategy card in place with **asset chips (BTC/ETH/SOL/BNB, multi-select)**
   + **5m/15m** timeframe toggle + "Crypto only" badge. Removed the stranded
   bottom timeframe section.
2. **Asset selection** — new `user_settings.selected_assets` (migration 050).
   Filters which crypto assets the bot trades; default = all four.
3. **Fetch-coverage fix (the functional unlock)** — `pm.get_crypto_short_markets()`
   fetches newest-created markets first (`order=startDate&ascending=false`),
   surfacing the currently-live candle markets with real in-window liquidity.
   Both crypto-short strategies now scan this universe. Verified live: 38 eligible
   5m markets, 21 with ≥ $2000 liquidity (BTC/ETH/SOL).

## 2. Current system architecture

```
selected_assets + selected_timeframe (user_settings, mig 049/050)
  -> signal_scan_job SELECT -> UserContext.{selected_timeframe,selected_assets}
  -> confluence_scalper.scan: pm.get_crypto_short_markets() gated by
     is_short_crypto_market(m, tf, assets)
  -> close_sweep: signal_scan_job pre-filters crypto_short_markets the same way
eligibility.is_short_crypto_market = asset-ticker match (optionally narrowed to
selected assets) + classified 5m/15m interval (fail-closed).
```

## 3. Files created / modified

Created:
- migrations/050_strategy_assets.sql
Modified:
- domain/strategy/eligibility.py (ASSET_ALIASES, market_matches_assets, assets arg)
- domain/strategy/types.py (UserContext.selected_assets)
- domain/strategy/strategies/confluence_scalper.py (get_crypto_short_markets + assets gate)
- integrations/polymarket.py (get_crypto_short_markets)
- services/signal_scan/signal_scan_job.py (SELECT, ctx, candle universe, close_sweep prefilter)
- webtrader/backend/schemas.py + router.py (selected_assets validate/persist/return)
- webtrader/frontend/src/lib/api.ts + pages/AutoTradePage.tsx (inline UI)
- tests/test_crypto_timeframe.py (asset tests), tests/test_confluence_scalper.py (mock target)

## 4. What is working

- 150 backend tests green; tsc + vite build clean; py_compile clean.
- Live Gamma probe confirms the fetch+gate surfaces tradeable candle markets.

## 5. Known issues

- Gamma caps `/markets` at 100 results/page; newest-first ordering still yields
  ample live candles (38 eligible). If coverage proves thin, paginate.
- Candle markets show liquidity=0 until they enter their short window — expected;
  the scanner re-fetches every 60s (cache ttl) so it catches them in-window.

## 6. What is next

- Apply migration 050 + redeploy; confirm positions open on live candles.
