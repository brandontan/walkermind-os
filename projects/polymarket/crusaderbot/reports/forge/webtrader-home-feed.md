# WARP•FORGE Report — webtrader-home-feed

Branch: WARP/webtrader-home-feed
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: WebTrader Home (DashboardPage) position rendering + new market-feed endpoint/component; PortfolioPage PositionRow value logic.
Not in Scope: trading engine open-position count / concurrency (left untouched per WARP🔹CMD — item 1 is UI-only); external crypto spot-price integration (blocked by env allowlist — item 5 news feed deferred); browser/visual QA (no headless UI here).
Suggested Next Step: WARP🔹CMD review; deploy and visually confirm on device, then revisit item 4 external-price/news once a host is allowlisted.

## 1. What was built

Owner raised five Home-screen items (screenshot). Implemented four; item 5 deferred per the env network limit.

- Item 2 — "status won tp kondisi minus": a WON · AWAITING REDEEM position showed a red minus PnL because the card valued it from the live CLOB mark (which can sit below entry). A confirmed win is now valued at its $1.00/share redeem payout, so it reads green/positive.
- Item 1 — "jika sudah on redeem hold posisi jgn di open position": won-but-not-redeemed positions are split out of the "Open Positions" list into a dedicated "Awaiting Redeem" strip (Force Redeem retained). UI-only; the engine's open-position count is unchanged (WARP🔹CMD decision).
- Item 3 — "open position auto slide jika position > 1": a new auto-advancing carousel cycles open-position cards (5s, pauses on hover/touch, dot indicators) when more than one is live.
- Item 4 — "info market feed realtime auto slide jd gak makan tempat": a compact, single-line auto-sliding market feed of the live BTC/ETH/SOL/BNB up/down candles, sourced from the already-synced markets table (Polymarket CLOB prices) via a new endpoint. No external spot-price dependency.
- Item 5 — news feed: DEFERRED. Requires an external news API; the environment egress proxy blocks non-allowlisted hosts (verified: Binance/Coingecko return `host_not_allowed`).

## 2. Current system architecture

Pipeline boundary unchanged — this lane is presentation + one read-only query endpoint.

```
markets table (CLOB-synced) --> GET /api/web/market-feed --> api.getMarketFeed()
                                                              --> <MarketFeed/> (auto-slide)
positions (status=open) --> api.getPositions("open") --> DashboardPage
   split: liveOpen (!awaiting_redeem)  --> <PositionCarousel> of <PositionRow>
          awaitingRedeem (awaiting_redeem) --> "Awaiting Redeem" strip + Force Redeem
PositionRow value: awaiting_redeem -> $1.00/share payout; else live mark; closed -> pnl_usdc
```

GET /api/web/market-feed: `DISTINCT ON (asset)` over `slug LIKE '%updown%'`, restricted to btc/eth/sol/bnb, `resolved=false`, `resolution_at > now()`, `yes_price NOT NULL`, `liquidity_usdc > 0`, nearest close per asset. Returns up_prob (=yes_price), lean (UP/DOWN/EVEN at 0.52/0.48), seconds_to_close, liquidity.

## 3. Files created / modified (full repo-root paths)

Created:
- projects/polymarket/crusaderbot/webtrader/frontend/src/components/PositionCarousel.tsx
- projects/polymarket/crusaderbot/webtrader/frontend/src/components/MarketFeed.tsx

Modified:
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx (PositionRow awaiting_redeem payout value)
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/DashboardPage.tsx (split list + carousel + market feed wiring)
- projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts (MarketFeedItem type + getMarketFeed)
- projects/polymarket/crusaderbot/webtrader/backend/router.py (GET /market-feed)
- projects/polymarket/crusaderbot/webtrader/backend/schemas.py (MarketFeedItem)

## 4. What is working

- `tsc && vite build` clean (883 modules transformed).
- `py_compile` clean on router.py + schemas.py.
- The /market-feed SQL verified live against Supabase — returns BTC/ETH/SOL/BNB nearest candles with yes_price/liquidity/countdown; off-target zero-liquidity assets (doge/hype/xrp) correctly excluded.
- Item 2 math: shares = size/entry; payout = shares × $1.00 = size/entry > size when entry < 1 → positive diff, green tone.

## 5. Known issues

- NOT browser-tested (no headless UI in this environment) — carousel motion, feed cadence, and the Awaiting Redeem strip need a visual check on deploy.
- Item 4 feed freshness is bounded by the scanner's markets-table sync cadence (it is not a per-request live CLOB call).
- Item 5 (news) and any external spot-price feed remain blocked until a host is added to the environment (and Fly) allowlist.

## 6. What is next

- WARP🔹CMD review + deploy; visual QA of the four items on device.
- If a richer feed is wanted, allowlist a price/news host and revisit items 4/5.
