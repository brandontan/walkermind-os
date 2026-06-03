# WARP•R00T — dashboard-ux

Branch: WARP/ROOT/dashboard-ux
Date: 2026-06-03 23:47 WIB
Role: WARP•R00T (build lane)
Tier: STANDARD · Claim: NARROW INTEGRATION

Owner-directed UI/UX pass on the WebTrader Home dashboard. Three asks:
1. Remove the Home 2x2 stat grid; keep only Win Rate, relocated into the scanner.
2. Playbook scanner showed only 2 markets — surface the REAL Polymarket sports board (no fake data).
3. When the market display exceeds 5 rows, render an animated carousel.

---

## 1. What was built

- **Stat grid removed / Win Rate relocated.** The Home `StatsGrid` (BALANCE / WIN RATE / PNL TODAY / SIGNALS in advanced mode; BALANCE / OPEN in essential) is removed from `DashboardPage`. Equity, today/7d/all-time PnL and balance already live in the `HeroCard` directly above it, so the grid was redundant. Win Rate — the one account metric not otherwise on Home — is now rendered inside the `ScannerPanel` stats strip, which becomes a 4-column row: `SCANNED · PUBLISHED · WIN RATE · LAST TICK`.

- **Playbook "only 2 markets" — root-caused and fixed at the display layer.** The dashboard `/market-feed` Sports branch read the `markets` DB table (`category ILIKE '%Sports%'`, `LIMIT 6`). That table's sports rows are populated solely by the scan job's `_sync_playbook_sports_markets`, which only upserts markets inside the (0, 2h] / (24h, 72h] **trade** windows. Polymarket's sports inventory is mostly far-dated, so the table ran near-empty and the panel showed whatever sparse sports-tagged rows existed. New helper `router._sports_market_feed_live()` now sources the feed **directly from Polymarket Gamma** (`get_events_with_markets`): real upcoming sports markets, sports-category filtered (reusing `playbook.SPORTS_CATEGORIES`), future-resolution only, nearest-event first, mapped to `MarketFeedItem`. It is decoupled from the trade window — **the bot's trading universe is unchanged**. A 45s in-process cache spares Gamma on the dashboard's frequent polls; any Gamma error is fail-soft to last-known (or empty) and never raises into the request.

- **MarketCarousel (display > 5).** `ScannerPanel` now renders the market list as a static block at ≤5 rows and as an auto-advancing carousel above that — pages of 5, 4.2s auto-advance, slide animation, progress bar, dot indicators + prev/next arrows, pause-on-hover. It mirrors the existing `SignalCarousel` so panel height stays fixed regardless of feed size.

- **Human countdown formatting.** `fmtSecs` now renders `Nd Hh` / `Hh Mm` for multi-hour/day TTLs instead of a five-digit minute count (the "82533m" the owner saw on far-dated sports markets). Crypto candles keep `Mm Ss`.

## 2. Current system architecture (relevant slice)

```
DashboardPage (HOME)
  HeroCard ........... equity / today / 7d / all-time / balance   (unchanged)
  [StatsGrid] ........ REMOVED
  ScannerPanel
     stats row ....... SCANNED · PUBLISHED · WIN RATE · LAST TICK  (winRate prop, NEW)
     terminal lines .. unchanged
     markets ......... feed ≤5 → static MarketRow list
                       feed >5 → MarketCarousel (pages of 5, animated)   NEW
     SignalCarousel .. unchanged

GET /api/web/market-feed  (router.get_market_feed)
  active_preset → _PRESET_LOCKED_CATEGORY
     Crypto  → _crypto_market_feed (DB, unchanged)
     Weather → _weather_market_feed (DB, unchanged)
     Sports  → _sports_market_feed_live (Gamma, NEW)  ← was _category_market_feed (DB)
     other   → _category_market_feed (DB, unchanged)

_sports_market_feed_live: Gamma get_events_with_markets(200)
   → filter SPORTS_CATEGORIES → future-resolution only → MarketFeedItem
   → sort nearest-event → cap 12 → 45s cache → fail-soft
```

Trading path (`select_sports_markets_in_window`, the scan job, the risk gate, execution, Kelly, `ENABLE_LIVE_TRADING`) is **untouched**.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — `_sports_market_feed_live` + `_coerce_price_list` helpers; `/market-feed` Sports branch routed to the live feed; 45s cache.
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/ScannerPanel.tsx` — `fmtSecs` d/h formatting; `MarketRow` + `MarketCarousel`; `winRate` prop + 4-col stats row; carousel-above-5 swap.
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/DashboardPage.tsx` — removed `StatsGrid` block + `StatCard`/`StatsGrid` imports; pass `winRate` to `ScannerPanel`.
- `projects/polymarket/crusaderbot/tests/test_market_feed_preset.py` — `test_sports_preset_uses_category_query` rewritten to `test_sports_preset_uses_live_gamma_feed` (asserts the live Gamma path, excludes past/non-sports, nearest-event order).

State:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- `npx tsc --noEmit` — 0 errors.
- `npm run build` (tsc && vite build) — clean (only the pre-existing PortfolioPage dynamic/static-import advisory).
- `ruff check webtrader/backend/router.py` — All checks passed.
- `python -m py_compile router.py` — clean.
- `pytest tests/test_market_feed_preset.py` — **17/17 pass**, including the rewritten Gamma-feed test (verifies sports markets come from Gamma, past/non-sports excluded, nearest-event ordering, and that neither the crypto `updown` query nor the DB `category ILIKE` query is used for Playbook).

## 5. Known issues

- Sports feed is live data, so the panel reflects whatever upcoming sports markets Gamma returns — if Polymarket genuinely has no upcoming sports markets at a moment, the panel will be sparse (correct behaviour, not a bug).
- This changes only the **display** of sports markets. The bot still scans/trades sports inside the existing (0,2h]/(24-72h] windows — by design, per owner direction (display-only, no trading change). Widening the trade universe remains a separate MAJOR lane if ever wanted.
- Runtime not exercised against a live Gamma endpoint in this session (no network-backed integration run); validated via hermetic test with a patched Gamma client. Confirm visually after Fly redeploy.
- `_SPORTS_FEED_CACHE` is a module-level dict (single worker process); fine for the current Fly single-worker deploy.

## 6. What is next

- WARP🔹CMD review + Fly.io redeploy (frontend rebuild + backend worker).
- Visually confirm on `crusaderbot.fly.dev`: Home no longer shows the stat grid; Win Rate sits in the scanner row; Playbook shows multiple real sports markets; >5 markets animate as a carousel; countdowns read `Nd Hh`.

---

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : Home dashboard render (stat-grid removal + Win Rate in scanner), /market-feed Sports branch sourcing real Gamma sports data, ScannerPanel MarketCarousel at feed >5, fmtSecs formatting.
Not in Scope      : Trading/scan market-selection windows, risk gate, execution, Kelly, ENABLE_LIVE_TRADING, the crypto/weather feed paths, non-Home pages.
Suggested Next    : WARP🔹CMD review + Fly redeploy. (STANDARD — WARP•SENTINEL not required; no execution/risk/capital surface touched.)
