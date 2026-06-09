# WARP•R00T — crypto-feed-freshness

Branch: WARP/ROOT/crypto-feed-freshness  (stacked on WARP/ROOT/scanner-market-detail / PR #1593)
Date: 2026-06-04 00:32 WIB
Role: WARP•R00T (investigate + build)
Tier: STANDARD · Claim: NARROW INTEGRATION

Owner report: the crypto scanner feed (Smart Strike preset) "looks like fake
data — liquidity never changes" (BTC 3% $17K / ETH 51% $11K / SOL 3% $2K, static).
Owner directed: add a freshness guard AND investigate the sync.

---

## 1. What was built (+ investigation verdict)

### Investigation — is it fake data? NO.

- **Real Polymarket Gamma data, not demo.** Demo/seed rows use `demo-market-*`
  slugs with `is_demo=TRUE`; the crypto feed query filters `slug LIKE '%updown%'`,
  which structurally excludes them. (`scripts/seed_demo_data.py`; `router.py`
  `_crypto_market_feed`.)
- **The sync is correct — no scan-loop bug.**
  `services/signal_scan/signal_scan_job.py:_upsert_crypto_window_markets`
  (730–798) sets `synced_at = NOW()` and updates `yes_price` / `no_price` /
  `liquidity_usdc` unconditionally on both INSERT and `ON CONFLICT DO UPDATE` —
  no WHERE/branch skips the refresh. It runs every scan tick (15s
  `run_close_sweep_fast` / 180s `run_once`) for every candle-preset user
  (`active_preset in _ALL_CANDLE_PRESETS`). A Gamma cache hit (45s TTL) does NOT
  short-circuit the upsert, so `synced_at` still refreshes each tick.
- **Why it looks frozen:** these short candle markets genuinely have thin, stable
  liquidity, and Gamma's `liquidity` field sits behind a 45s cache, so the number
  barely moves second-to-second — real, just stable. BTC/SOL both 3% is a real low
  up-probability, not a `0.5` default. Identical "2m 17s" = they share one candle
  close window.
- **The one true staleness risk:** if **no candle-preset user is active**, the
  sync never runs (gated on `_ALL_CANDLE_PRESETS`) — and the feed query had **no
  freshness guard**, so it kept returning the last-synced rows: a frozen snapshot
  that reads exactly like fake data until the window's `resolution_at` passes.

### Fix (display layer)

Added `AND synced_at > now() - interval '5 minutes'` to the DB-backed feeds
`_crypto_market_feed` and `_weather_market_feed`. The per-scan sync keeps
`synced_at` within ≤180s for active candle users, so live rows always pass; a
**stalled sync** now drops out → the scanner shows "awaiting signal — scanning
live markets…" instead of a frozen snapshot. No trading-path change.

## 2. Current system architecture (relevant slice)

```
GET /api/web/market-feed
  Crypto  → _crypto_market_feed   (DB markets, slug %updown%)  + synced_at < 5m guard  ← NEW
  Weather → _weather_market_feed  (DB markets, category=Weather) + synced_at < 5m guard ← NEW
  Sports  → _sports_market_feed_live (live Gamma, already fresh — no guard needed)
  other   → _category_market_feed (DB) — left as-is (synced_at maintenance varies)

markets table ← _upsert_crypto_window_markets (every scan tick, candle users)
                sets synced_at=NOW(), refreshes yes_price/liquidity_usdc
```

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — `synced_at` freshness guard in `_crypto_market_feed` + `_weather_market_feed` (+ rationale comment).
- `projects/polymarket/crusaderbot/tests/test_market_feed_preset.py` — `test_crypto_feed_has_freshness_guard`.

State:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- `python -m py_compile` + `ruff check` — clean.
- `pytest tests/test_market_feed_preset.py` — **23/23 pass** (incl. the new freshness-guard assertion; all prior crypto/weather/sports/preset tests unchanged).

## 5. Known issues

- The guard does **not** change what the owner currently sees (their candle preset is active, so rows are fresh) — it only prevents the frozen-snapshot failure mode when the sync stalls. The static liquidity in the owner's screenshot is genuinely thin candle liquidity + Gamma's 45s cache, not staleness.
- 5-minute threshold chosen as ~1.7× the 180s main-scan interval (margin for a slow/skipped tick). If `SIGNAL_SCAN_INTERVAL` is raised materially, revisit.
- `_category_market_feed` (generic, non-sports) was intentionally NOT guarded — synced_at maintenance for general-sync rows is not guaranteed and a guard could wrongly empty it.

## 6. What is next

- WARP🔹CMD review + Fly redeploy. **Depends on #1593** (same `router.py`); merge #1593 first, then this.
- Owner decision (NOT done here — touches the trading data path, MAJOR): for liquidity that visibly *moves*, either cut `_CRYPTO_WINDOW_CACHE_TTL` (45s) or read live CLOB depth at display time. Optional UX add: a per-feed "synced Ns ago" freshness chip so liveness is visible at a glance.

---

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : `_crypto_market_feed` / `_weather_market_feed` freshness guard; verdict that the crypto sync refreshes correctly.
Not in Scope      : the scan loop / `_upsert_crypto_window_markets` (verified correct, unchanged); Gamma cache TTL; CLOB live-price reads; risk/execution/Kelly.
Suggested Next    : WARP🔹CMD review + Fly redeploy after #1593. (STANDARD — WARP•SENTINEL not required.)
