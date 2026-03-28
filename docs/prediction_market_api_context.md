# Prediction Market Intelligence API — Developer Context

> Drop this file into Claude or ChatGPT to get full assistance with the API.
> The AI will understand every endpoint, parameter, and use case.

---

## Overview

This API provides access to a comprehensive prediction market intelligence database covering **Polymarket**, **Kalshi**, and **real-time social signals**. All endpoints share a single base URL and request format.

**Base URL:** `https://narrative.agent.heisenberg.so`  
**Single endpoint for all calls:** `POST /api/v2/semantic/retrieve/parameterized`  
**Full Postman docs:** https://documenter.getpostman.com/view/51012794/2sBXVZnu99

---

## Universal Request Structure

Every API call uses the same endpoint and the same JSON body shape:

```json
{
  "agent_id": <number>,       // identifies which data source to query
  "params": { ... },          // filters specific to each endpoint
  "pagination": {             // optional; include when paginating
    "limit": 50,
    "offset": 0
  },
  "formatter_config": {
    "format_type": "raw"      // always use "raw"
  }
}
```

**Key points:**
- The `agent_id` is fixed per endpoint — do not change it.
- All `params` values are strings unless noted otherwise.
- `pagination.limit` max is **200** for all endpoints.
- Timestamps are **Unix seconds** unless the param description says otherwise.
- Omit optional params entirely (or set to `null`) to skip filtering.

---

## Endpoints

---

### 1. Polymarket Markets
**agent_id: 574**

Search and filter Polymarket markets by volume, condition, slug, or date range.

```json
POST /api/v2/semantic/retrieve/parameterized
{
  "agent_id": 574,
  "params": {
    "min_volume": "100",
    "condition_id": "0xeaff81...",
    "market_slug": "will-trump-win-2024",
    "end_date_min": "1768467703",
    "end_date_max": "1769213303",
    "closed": "True"
  },
  "pagination": { "limit": 100, "offset": 0 },
  "formatter_config": { "format_type": "raw" }
}
```

**Parameters:**
| Param | Type | Description |
|---|---|---|
| `min_volume` | string | Minimum total volume in USD |
| `condition_id` | string | Exact hex condition ID for a single market |
| `market_slug` | string | URL-style slug (e.g. `will-trump-win-2024`) |
| `end_date_min` | string | Unix timestamp — earliest resolution date |
| `end_date_max` | string | Unix timestamp — latest resolution date |
| `closed` | string | `"True"` or `"False"` — filter by market status |

**Use cases:**
- Find all open markets with >$10k volume
- Look up a specific market by slug to get its `condition_id` (needed for trade/PnL queries)
- Discover markets resolving within a specific window

---

### 2. Polymarket Trades
**agent_id: 556**

Historical trade feed for Polymarket. Filter by wallet, market, direction, or time.

```json
POST /api/v2/semantic/retrieve/parameterized
{
  "agent_id": 556,
  "params": {
    "wallet_proxy": "0xabc123...",
    "condition_id": "0xeaff81...",
    "market_slug": "will-trump-win-2024",
    "side": "BUY",
    "start_time": "1767973812",
    "end_time": "1767973860"
  },
  "pagination": { "limit": 100, "offset": 0 },
  "formatter_config": { "format_type": "raw" }
}
```

**Parameters:**
| Param | Type | Description |
|---|---|---|
| `wallet_proxy` | string | Wallet address, or `"ALL"` for all wallets |
| `condition_id` | string | Hex condition ID, or `"ALL"` for all markets |
| `market_slug` | string | URL slug to filter by market |
| `side` | string | `"BUY"` or `"SELL"` |
| `start_time` | string | Unix timestamp (seconds) |
| `end_time` | string | Unix timestamp (seconds) |

**Use cases:**
- Reconstruct a wallet's full trade history in a market
- Detect large buy flows entering a market (smart money signal)
- Monitor a copy-trading target's recent entries in real time
- Audit a market for wash trading (filter by condition_id, look for repetitive wallet patterns)

---

### 3. Polymarket Candlesticks
**agent_id: 568**

OHLCV candlestick data for any Polymarket outcome token.

```json
POST /api/v2/semantic/retrieve/parameterized
{
  "agent_id": 568,
  "params": {
    "token_id": "58639447033085668146701215689433308999613524738987821507545529427932862502961",
    "interval": "1m",
    "start_time": "1769219100",
    "end_time": "1769508420"
  },
  "formatter_config": { "format_type": "raw" }
}
```

**Parameters:**
| Param | Type | Required | Description |
|---|---|---|---|
| `token_id` | string | **Yes** | Token ID of the YES or NO outcome token |
| `interval` | string | No | `"1m"`, `"5m"`, `"1h"`, or `"1d"` (default: `"1m"`) |
| `start_time` | string | No | Unix timestamp (seconds) |
| `end_time` | string | No | Unix timestamp (seconds) |

> **Note on token_id:** Each Polymarket market has two tokens — YES and NO — each with a distinct token_id. Retrieve them via the Polymarket Markets endpoint or from trade records.

**Use cases:**
- Chart historical price movement for a market outcome
- Compute technical indicators (RSI, MACD, Bollinger Bands) on prediction market prices
- Detect price momentum before entering a position
- Correlate price spikes with external news events
- Train ML models on prediction market price series

---

### 4. Polymarket Orderbook
**agent_id: 572**

Historical order book snapshots for a Polymarket outcome token.

```json
POST /api/v2/semantic/retrieve/parameterized
{
  "agent_id": 572,
  "params": {
    "token_id": "69435545313357346912686520645149775930858973121193492847015767460308803044235",
    "start_time": "1769902905868",
    "end_time": "1770034843377"
  },
  "formatter_config": { "format_type": "raw" }
}
```

**Parameters:**
| Param | Type | Required | Description |
|---|---|---|---|
| `token_id` | string | **Yes** | Token ID of the outcome token |
| `start_time` | string | No | Unix timestamp (seconds) |
| `end_time` | string | No | Unix timestamp (seconds) |

**Use cases:**
- Measure bid-ask spread history and available liquidity
- Detect sudden order book changes (informed trading signal)
- Screen markets for sufficient depth before executing a trade
- Combine with candlestick data for full market microstructure analysis

---

### 5. Polymarket PnL
**agent_id: 569**

Realized PnL time series for a wallet. Optionally scoped to a single market.

> **Important:** Returns **realized gains only** — open/unrealized positions are excluded.

```json
POST /api/v2/semantic/retrieve/parameterized
{
  "agent_id": 569,
  "params": {
    "granularity": "1d",
    "wallet": "0x8e433d051bfb5cc6a1f7e5a0452029b7ffb4a3cd",
    "start_time": "2026-02-10",
    "end_time": "2026-02-28"
  },
  "formatter_config": { "format_type": "raw" }
}
```

**Parameters:**
| Param | Type | Required | Description |
|---|---|---|---|
| `wallet` | string | **Yes** | Proxy wallet address |
| `granularity` | string | No | `"1d"`, `"1w"`, or `"1m"` (default: `"1d"`) |
| `start_time` | string | No | Date as `YYYY-MM-DD` (note: **not** Unix timestamp) |
| `end_time` | string | No | Date as `YYYY-MM-DD` |
| `condition_id` | string | No | Hex condition ID to scope PnL to one market |

**Use cases:**
- Chart a wallet's equity curve over time
- Compute rolling performance metrics (Sharpe, win rate) over custom windows
- Verify a wallet's claimed performance history before copy-trading
- Build trader profile pages with PnL charts
- Scope PnL to a single market to see per-market contribution

---

### 6. Polymarket Leaderboard
**agent_id: 579**

Official Polymarket PnL-based leaderboard. Rank traders by profit over 1d, 1w, or all-time.

```json
POST /api/v2/semantic/retrieve/parameterized
{
  "agent_id": 579,
  "params": {
    "wallet_address": "ALL",
    "leaderboard_period": "1d"
  },
  "pagination": { "limit": 50, "offset": 0 },
  "formatter_config": { "format_type": "raw" }
}
```

**Parameters:**
| Param | Type | Description |
|---|---|---|
| `wallet_address` | string | Specific wallet address, or `"ALL"` for full leaderboard |
| `leaderboard_period` | string | `"1d"`, `"3d"`, `"7d"`, `"30d"` |

**Use cases:**
- Surface top earners for a given time window
- Look up where a specific wallet ranks
- Cross-reference with the H-Score leaderboard (wallets appearing in both = strong signal)
- Display trader rankings in a product UI

---

### 7. H-Score Leaderboard (Proprietary)
**agent_id: 584**

Proprietary trader ranking system. H-Score identifies **consistently skilled** traders across multiple time horizons — it filters out bots, lucky streaks, and wash traders in ways that raw PnL rankings cannot.

```json
POST /api/v2/semantic/retrieve/parameterized
{
  "agent_id": 584,
  "params": {
    "min_win_rate_15d": "0.45",
    "max_win_rate_15d": "0.95",
    "min_roi_15d": "0",
    "min_total_trades_15d": "50",
    "max_total_trades_15d": "100000",
    "min_pnl_15d": "5000",
    "sort_by": "roi"
  },
  "pagination": { "limit": 50, "offset": 0 },
  "formatter_config": { "format_type": "raw" }
}
```

**Parameters:**
| Param | Type | Description |
|---|---|---|
| `min_win_rate_15d` | string | Minimum 15-day win rate (0.0–1.0, e.g. `"0.45"` for 45%+) |
| `max_win_rate_15d` | string | Maximum 15-day win rate — set e.g. `"0.95"` to exclude suspiciously perfect traders |
| `min_roi_15d` | string | Minimum 15-day ROI — set `"0"` for profitable traders only |
| `min_pnl_15d` | string | Minimum realized PnL in USD over 15 days |
| `min_total_trades_15d` | string | Minimum trade count — ensures sufficient activity |
| `max_total_trades_15d` | string | Maximum trade count — use to exclude bots (e.g. `"100000"`) |
| `sort_by` | string | Sort column: `"roi"`, `"win_rate"`, `"pnl"`, or default H-Score |

**Filter strategy for copy-trading:**
```
min_win_rate_15d: "0.45"      // at least 45% win rate
max_win_rate_15d: "0.92"      // exclude suspiciously perfect traders
min_roi_15d: "0"              // profitable only
min_total_trades_15d: "30"    // active enough to be meaningful
max_total_trades_15d: "5000"  // not a bot
```

**Use cases:**
- Find high-signal copy-trading candidates
- Build a watchlist of wallets to monitor for new entries
- Screen for genuinely skilled traders (not just lucky or high-volume)
- Power a copy-trading alert system

---

### 8. Wallet 360
**agent_id: 581**

Full 360-degree profile of any Polymarket wallet. 60+ performance, risk, behavioral, and activity metrics in a single call.

```json
POST /api/v2/semantic/retrieve/parameterized
{
  "agent_id": 581,
  "params": {
    "proxy_wallet": "0x8dbf0de58835c4827ba77669b5155980d1a053be",
    "window_days": "3"
  },
  "pagination": { "limit": 100, "offset": 0 },
  "formatter_config": { "format_type": "raw" }
}
```

**Parameters:**
| Param | Type | Required | Description |
|---|---|---|---|
| `proxy_wallet` | string | **Yes** | Wallet address to profile |
| `window_days` | string | **Yes** | Lookback window. Allowed values: `"1"`, `"3"`, `"7"`, `"15"` only (from Postman collection). |

**Returns (60+ metrics including):**
- PnL, ROI, win rate, trade count
- Average bet size, max drawdown
- Market diversity (how many different markets they trade)
- Activity patterns (time-of-day, frequency)
- Behavioral flags (bot-like patterns, concentration risk)
- Category specialization (politics, crypto, sports, etc.)

**Use cases:**
- Full due-diligence audit of a trader before copy-trading
- Build trader profile pages in your product
- Detect behavioral anomalies and bot patterns
- Analyze a trader's risk profile (drawdown, bet sizing, diversification)
- Feed wallet metrics into an AI agent's decision-making layer

---

### 9. Polymarket Market Insights
**agent_id: 575**

Market quality and structure metrics: liquidity scores, volume dynamics, whale concentration, and unique trader participation. Use this to distinguish genuinely contested markets from thin, illiquid, or manipulated ones.

```json
POST /api/v2/semantic/retrieve/parameterized
{
  "agent_id": 575,
  "params": {
    "min_volume_24h": "10000",
    "min_liquidity_percentile": "75",
    "volume_trend": "UP",
    "min_top1_wallet_pct": "0",
    "max_unique_traders_7d": "0"
  },
  "formatter_config": { "format_type": "raw" }
}
```

**Parameters:**
| Param | Type | Description |
|---|---|---|
| `min_volume_24h` | string | Minimum 24h volume in USD |
| `min_liquidity_percentile` | string | Minimum liquidity percentile (0–100). `"75"` = top quartile |
| `volume_trend` | string | `"UP"`, `"DOWN"`, or `"ALL"` |
| `min_top1_wallet_pct` | string | Min % of position held by top wallet — finds whale-dominated markets |
| `max_unique_traders_7d` | string | Max unique traders in 7 days — finds niche/illiquid markets |

**Use cases:**
- Screen markets for sufficient liquidity before trading
- Find markets with rising volume momentum (trending opportunities)
- Flag whale-dominated markets where one wallet controls pricing
- Discover emerging markets with growing participation
- Filter illiquid markets out of copy-trading or arbitrage pipelines
- Build a market discovery feed sorted by quality metrics

---

### 10. Kalshi Markets
**agent_id: 565**

Search and browse the Kalshi market catalog. Filter by ticker, event, keyword, or status.

```json
POST /api/v2/semantic/retrieve/parameterized
{
  "agent_id": 565,
  "params": {
    "ticker": "KXUFCFIGHT-25OCT25ASPGAN-ASP",
    "event_ticker": "KXUFCFIGHT-25OCT25ASPGAN",
    "title": "Bitcoin",
    "status": "open",
    "close_time_min": "1326484980",
    "close_time_max": "2209492980"
  },
  "pagination": { "limit": 20, "offset": 0 },
  "formatter_config": { "format_type": "raw" }
}
```

**Parameters:**
| Param | Type | Description |
|---|---|---|
| `ticker` | string | Exact Kalshi market ticker |
| `event_ticker` | string | Parent event ticker — returns all markets under an event |
| `title` | string | Keyword search in market title |
| `status` | string | `"open"`, `"closed"`, or `"finalized"` |
| `close_time_min` | string | Unix timestamp — earliest close time |
| `close_time_max` | string | Unix timestamp — latest close time |

**Use cases:**
- Find Kalshi markets covering the same event as a Polymarket market (for arbitrage)
- Browse all open markets in a category
- Discover markets closing within a specific window
- Monitor settlement status for finalized markets

---

### 11. Kalshi Trades
**agent_id: 573**

Historical trade records for Kalshi markets.

```json
POST /api/v2/semantic/retrieve/parameterized
{
  "agent_id": 573,
  "params": {
    "ticker": "KXBTC15M-26FEB030730-30",
    "start_time": "1770121317",
    "end_time": "1770121748"
  },
  "pagination": { "limit": 10, "offset": 0 },
  "formatter_config": { "format_type": "raw" }
}
```

**Parameters:**
| Param | Type | Description |
|---|---|---|
| `ticker` | string | Exact Kalshi market ticker |
| `start_time` | string | Unix timestamp (seconds) |
| `end_time` | string | Unix timestamp (seconds) |

**Use cases:**
- Analyze trade flow in a Kalshi market
- Compare Kalshi and Polymarket prices for the same event
- Detect settlement gaps (price discrepancies at market close)
- Feed Kalshi data into cross-exchange arbitrage detection pipelines

---

### 12. Social Pulse
**agent_id: 585**

Retrieves a parameterized set of social media posts (tweets) matching specified keywords within a given time window. Use this as a **leading indicator** before analyzing price action — social signals often move before markets reprice.

```json
POST /api/v2/semantic/retrieve/parameterized
{
  "agent_id": 585,
  "params": {
    "keywords": "{Trump,election,MAGA}",
    "hours_back": "12"
  },
  "formatter_config": { "format_type": "raw" }
}
```

**Parameters:**
| Param | Type | Required | Description |
|---|---|---|---|
| `keywords` | string | **Yes** | Comma-separated keywords **wrapped in curly braces**. Example: `"{Trump,election,MAGA}"` or `"{NHL,hockey,Stanley Cup}"`. Do not add spaces between keywords. |
| `hours_back` | string | **Yes** | Number of hours to look back for posts. Example: `"12"`. Passed as a string, not an integer. |

**Key metrics returned and how to interpret them:**

| Metric | What it means |
|---|---|
| `acceleration` | Momentum score. `>1.0` = mentions are rising, `<1.0` = fading |
| `author_diversity_pct` | % of unique authors. `>50%` = organic conversation. `<20%` = likely bot-driven — treat as noise |
| `pct_last_1h` | % of all mentions in the last 1 hour |
| `pct_last_6h` | % of all mentions in the last 6 hours |
| `tweet_count` | Total matching posts in the window |
| `like_count` / `retweet_count` / `reply_count` | Per-post engagement. High `reply_count` relative to likes often signals controversy |

**Reading the momentum signal:**
- `pct_last_1h` high relative to `pct_last_6h` → topic is **surging right now**
- `pct_last_1h` low but `pct_last_6h` high → momentum is **fading**
- High `acceleration` + high `author_diversity_pct` → **real signal**, act on it
- High `acceleration` + low `author_diversity_pct` → **coordinated noise**, ignore it

**Use cases:**
- Gauge narrative momentum before analyzing a market's price
- Detect breaking news before it is priced into markets
- Validate a trading thesis with organic public sentiment
- Identify surging topics to discover which markets to watch
- Combine with Polymarket Candlesticks to correlate news spikes with price moves
- Monitor geopolitical or macro topics (tariffs, elections, central banks, crypto news)
- Filter bot-driven social noise from genuine sentiment

---

## Common Workflows

### Copy-Trading Pipeline
The goal is to identify skilled traders, validate them, and detect their new positions early.

```
Step 1: H-Score Leaderboard (agent_id 584)
        → Filter: min_win_rate=0.45, max_win_rate=0.92, min_roi=0, max_trades=5000
        → Output: shortlist of high-signal wallet addresses

Step 2: Wallet 360 (agent_id 581)
        → For each candidate: full risk/behavioral profile
        → Flag: bot patterns, low market diversity, erratic bet sizing

Step 3: Polymarket Trades (agent_id 556)
        → Filter by wallet_proxy + recent start_time
        → Detect: what markets they've entered in the last 24–48 hours

Step 4: Polymarket Market Insights (agent_id 575)
        → For each market they're in: check liquidity and volume trend
        → Discard: markets with thin liquidity or whale-dominated order books

Step 5: Social Pulse (agent_id 585)
        → Keywords: topic of the markets they're entering
        → Validate: high acceleration + high author_diversity = thesis confirmed

Step 6: Polymarket Candlesticks (agent_id 568)
        → Check price history on the markets they entered
        → Look for: early entry before price movement
```

---

### Cross-Exchange Arbitrage
Detect price discrepancies between Kalshi and Polymarket on the same event.

```
Step 1: Kalshi Markets (agent_id 565)
        → status: "open" — get active markets

Step 2: Polymarket Markets (agent_id 574)
        → Match by topic/title — find corresponding Polymarket markets

Step 3: Kalshi Trades (agent_id 573) + Polymarket Trades (agent_id 556)
        → Compare recent trade prices on both sides
        → Flag: divergence > 3–5 cents on the same binary outcome

Step 4: Polymarket Market Insights (agent_id 575)
        → Verify the Polymarket side has enough liquidity to trade the arb

Step 5: Polymarket Candlesticks (agent_id 568)
        → Confirm historical spread and timing of past divergences
```

---

### Market Intelligence Dashboard
Build a ranked, filtered view of the most tradeable markets with social context.

```
Step 1: Social Pulse (agent_id 585)
        → keywords: "{Politics,crypto,Bitcoin}" (or topic of interest, in curly braces)
        → Filter: acceleration > 1.2, author_diversity_pct > 40%

Step 2: Polymarket Market Insights (agent_id 575)
        → volume_trend: "UP", min_liquidity_percentile: "75"
        → Match trending topics to liquid markets

Step 3: Polymarket Candlesticks (agent_id 568)
        → Fetch 1d candles for top markets — render sparklines

Step 4: Polymarket Trades (agent_id 556)
        → Recent large trades per market — shows where smart money is flowing

Step 5: Kalshi Markets (agent_id 565)
        → Cross-reference for Kalshi equivalents
```

---

### Trader Profile Page
Full data for displaying a trader's stats in a product.

```
Step 1: Wallet 360 (agent_id 581)
        → 60+ metrics: PnL, ROI, win rate, risk profile, behavioral flags

Step 2: Polymarket PnL (agent_id 569)
        → Daily granularity, 90-day window → equity curve chart

Step 3: Polymarket Trades (agent_id 556)
        → Latest 50 trades → activity feed

Step 4: Polymarket Leaderboard (agent_id 579)
        → wallet_address set to target → get their official rank
```

---

### Settlement Gap Scanner
Identify markets where price hasn't yet moved to reflect resolution.

```
Step 1: Kalshi Markets (agent_id 565)
        → status: "finalized" — recently resolved markets

Step 2: Polymarket Markets (agent_id 574)
        → Find matching Polymarket markets (still open or recently closed)

Step 3: Polymarket Candlesticks (agent_id 568)
        → Check if Polymarket price has converged to 0 or 1 yet

Step 4: Polymarket Orderbook (agent_id 572)
        → Confirm there is still available liquidity to trade the gap
```

---

### Breaking News Trading Signal
Use social intelligence to front-run market repricing.

```
Step 1: Social Pulse (agent_id 585)
        → keywords: "{election,Trump,MAGA}" or topic of interest (in curly braces)
        → Check: acceleration > 1.5, author_diversity_pct > 40%
        → If both true: real signal, move fast

Step 2: Polymarket Markets (agent_id 574)
        → Find markets related to the trending topic

Step 3: Polymarket Candlesticks (agent_id 568)
        → Check if price has already moved
        → If not: potential entry opportunity before repricing

Step 4: Polymarket Market Insights (agent_id 575)
        → Verify liquidity before acting
```

---

## Quick Reference — Agent IDs

| Endpoint | agent_id | Key Required Param |
|---|---|---|
| Polymarket Markets | 574 | — (all optional) |
| Polymarket Trades | 556 | — (all optional) |
| Polymarket Candlesticks | 568 | `token_id` |
| Polymarket Orderbook | 572 | `token_id` |
| Polymarket PnL | 569 | `wallet` |
| Polymarket Leaderboard | 579 | — |
| H-Score Leaderboard | 584 | — |
| Wallet 360 | 581 | `proxy_wallet` |
| Polymarket Market Insights | 575 | — |
| Kalshi Markets | 565 | — |
| Kalshi Trades | 573 | — |
| Social Pulse | 585 | `keywords` (in curly braces) |

---

## Pagination

All endpoints that return lists support pagination via the top-level `pagination` object:

```json
"pagination": {
  "limit": 100,   // max 200
  "offset": 0     // increment by limit for next page
}
```

To retrieve all results, loop until the number of returned records is less than `limit`.

---

## Timestamp Formats

- Most endpoints use **Unix timestamps in seconds** for `start_time` / `end_time`
- **Exception:** Polymarket PnL uses `YYYY-MM-DD` date strings (e.g. `"2026-02-10"`)

**Generate Unix timestamps:**
```javascript
// JavaScript
const now = Math.floor(Date.now() / 1000);
const last24h = now - 86400;
const last7d = now - 604800;
```
```python
# Python
import time
now = int(time.time())
last_24h = now - 86400
```

---

## Notes for AI Assistants

When a developer asks you to help with this API:

1. **Always include `"formatter_config": { "format_type": "raw" }`** in every request body.
2. **agent_id is fixed** per endpoint — never change it.
3. **All params are strings** even when the value is a number (e.g. `"100"` not `100`), unless the param is in `pagination` (where integers are correct).
4. When the developer needs a `condition_id` or `token_id` they don't have, suggest they first call Polymarket Markets (agent_id 574) with a `market_slug` to retrieve it.
5. For copy-trading use cases, always suggest starting with **H-Score Leaderboard (584)** rather than Polymarket Leaderboard (579) — H-Score filters out bots and lucky streaks.
6. PnL dates use `YYYY-MM-DD` format, not Unix timestamps — this is the only exception among params.
7. When paginating, increment `offset` by the `limit` value each call, stop when results returned < limit.
8. **Social Pulse (585):** `keywords` must be comma-separated and **wrapped in curly braces**, e.g. `"{Trump,election,MAGA}"`. Do not add spaces between keywords. `hours_back` is a string (e.g. `"12"`).
9. For social signals: `acceleration > 1.0` means rising momentum. Always check `author_diversity_pct` — if it's below 20%, the signal is likely noise regardless of acceleration.
