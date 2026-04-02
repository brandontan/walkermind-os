---
name: polymarket-bot-builder
description: >
  Specialized skill for building production-grade Polymarket trading bots.
  Use when building, debugging, or improving any Polymarket trading system,
  signal engine, risk management, order execution, or bot infrastructure.
  Triggers on: polymarket bot, CLOB execution, trading signal, Kelly sizing,
  Bayesian signal, paper trading, Polymarket API, prediction market bot.
---

# Polymarket Bot Builder Skill

## Project Context

**Repo:** github.com/bayuewalker/walker-ai-team
**Bot location:** projects/polymarket/polyquantbot/
**Owner:** Bayue Walker — sole decision maker

---

## Architecture Overview

```
MARKET DATA (Gamma API + CLOB WebSocket)
        ↓
SIGNAL ENGINE (Bayesian EV + edge filter)
        ↓
RISK GATE (SENTINEL — hard gate)
        ↓
ORDER MANAGER (dedup + idempotency)
        ↓
EXECUTION (CLOB paper/live)
        ↓
STATE (SQLite → PostgreSQL)
        ↓
NOTIFICATIONS (Telegram)
        ↓
ANALYTICS (metrics + reports)
```

---

## Core APIs

### Polymarket Gamma API
```python
BASE_URL = "https://gamma-api.polymarket.com"

# Get markets
GET /markets
params: limit, offset, active, closed, 
        order, ascending, tag_slug

# Get single market
GET /markets/{condition_id}

# Get events
GET /events
params: limit, offset, active, closed
```

### Polymarket CLOB API
```python
BASE_URL = "https://clob.polymarket.com"

# Get order book
GET /book?token_id={token_id}

# Place order (requires auth)
POST /order
body: {
  "order": {
    "salt": int,
    "maker": "0x...",
    "signer": "0x...", 
    "taker": "0x0000...0000",
    "tokenId": "string",
    "makerAmount": "string",  # USDC (6 decimals)
    "takerAmount": "string",  # shares
    "expiration": "0",
    "nonce": "0",
    "feeRateBps": "0",
    "side": "BUY|SELL",
    "signatureType": 0
  },
  "signature": "0x...",
  "orderType": "GTC|GTD|FOK",
  "owner": "api_key"
}

# Get open orders
GET /orders?owner={api_key}&market={condition_id}

# Cancel order
DELETE /order/{order_id}
```

### Intelligence API (Falcon/Heisenberg)
```python
BASE_URL = "https://narrative.agent.heisenberg.so"
ENDPOINT = "POST /api/v2/semantic/retrieve/parameterized"

# Key agent IDs:
# 574 → Polymarket Markets
# 556 → Polymarket Trades  
# 568 → Candlesticks (token_id required)
# 572 → Orderbook
# 569 → PnL (wallet required)
# 584 → H-Score Leaderboard
# 585 → Social Pulse (keywords in {curly braces})
# 565 → Kalshi Markets
# 573 → Kalshi Trades
```

---

## Core Formulas (implement exactly)

```python
# Expected Value
def calculate_ev(p_model: float, decimal_odds: float) -> float:
    b = decimal_odds - 1
    return p_model * b - (1 - p_model)

# Market Edge  
def calculate_edge(p_model: float, p_market: float) -> float:
    return p_model - p_market  # enter if > 0

# Mispricing Z-score
def calculate_zscore(p_model: float, p_market: float, 
                     sigma: float) -> float:
    return (p_model - p_market) / sigma  # enter if > 1.5

# Kelly Criterion — ALWAYS USE FRACTIONAL
def calculate_kelly(p: float, b: float, 
                    alpha: float = 0.25) -> float:
    q = 1 - p
    full_kelly = (p * b - q) / b
    return alpha * full_kelly  # NEVER full Kelly!

# Max Drawdown
def calculate_mdd(peak: float, trough: float) -> float:
    return (peak - trough) / peak
```

---

## Risk Rules (enforce in code, never skip)

```python
RISK_CONFIG = {
    "max_position_pct": 0.10,      # 10% bankroll
    "max_concurrent_positions": 5,
    "daily_loss_limit": -2000.0,   # USD pause
    "max_drawdown_pct": 0.08,      # 8% block all
    "kelly_fraction": 0.25,        # NEVER full Kelly
    "min_liquidity_usd": 10_000.0,
    "min_ev_threshold": 0.0,
    "correlation_limit": 0.40,
    "price_min": 0.05,
    "price_max": 0.95,
}

# SENTINEL check before every order
def check_risk(order, portfolio, market) -> tuple[bool, str]:
    if order.size > portfolio.balance * RISK_CONFIG["max_position_pct"]:
        return False, "Exceeds max position size"
    if portfolio.daily_pnl < RISK_CONFIG["daily_loss_limit"]:
        return False, "Daily loss limit hit"
    if market.liquidity < RISK_CONFIG["min_liquidity_usd"]:
        return False, "Insufficient liquidity"
    if portfolio.drawdown > RISK_CONFIG["max_drawdown_pct"]:
        return False, "Max drawdown exceeded"
    return True, "APPROVED"
```

---

## Engineering Patterns

### Async Main Loop
```python
async def main():
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(
            market_scan_loop(session),
            arb_scanner_loop(session),
            position_monitor_loop(session),
            report_loop(),
        )

asyncio.run(main())
```

### Retry Pattern (mandatory on all external calls)
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10)
)
async def fetch_markets(session: aiohttp.ClientSession) -> list:
    async with session.get(
        f"{GAMMA_URL}/markets",
        timeout=aiohttp.ClientTimeout(total=10)
    ) as resp:
        resp.raise_for_status()
        return await resp.json()
```

### Dedup Pattern (mandatory on all orders)
```python
import hashlib

def generate_order_id(market_id: str, side: str, 
                       price: float, size: float) -> str:
    key = f"{market_id}:{side}:{price}:{size}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]

async def place_order_safe(order: Order, db: Database):
    order_id = generate_order_id(
        order.market_id, order.side, 
        order.price, order.size
    )
    if await db.order_exists(order_id):
        logger.warning("duplicate_order_rejected", 
                       order_id=order_id)
        return None
    await db.record_order(order_id)
    return await execute_order(order)
```

### Structured Logging (mandatory everywhere)
```python
import structlog

logger = structlog.get_logger()

# Every critical action:
logger.info("order_placed", 
    market_id=market_id,
    side=side,
    size=size,
    price=price,
    ev=ev,
    edge=edge,
    kelly_f=kelly_f,
    sentinel_approved=True,
    timestamp=datetime.utcnow().isoformat()
)
```

---

## Telegram Integration

```python
TELEGRAM_TEMPLATES = {
    "trade_open": (
        "🟢 TRADE OPENED\n"
        "Market: {market_title}\n"
        "Side: {side} @ {price:.2%}\n"
        "Size: ${size:.2f}\n"
        "EV: {ev:.3f} | Edge: {edge:.3f}\n"
        "Kelly: {kelly_f:.3f}"
    ),
    "trade_closed": (
        "🔴 TRADE CLOSED\n"
        "Market: {market_title}\n"
        "Exit: {exit_price:.2%}\n"
        "PnL: ${pnl:.2f} ({pnl_pct:.1%})\n"
        "Reason: {exit_reason}"
    ),
    "risk_alert": (
        "⚠️ RISK ALERT\n"
        "Type: {alert_type}\n"
        "Value: {value}\n"
        "Limit: {limit}\n"
        "Action: {action}"
    ),
    "daily_summary": (
        "📊 DAILY SUMMARY\n"
        "P&L: ${daily_pnl:.2f}\n"
        "Trades: {trade_count}\n"
        "Win Rate: {win_rate:.1%}\n"
        "Portfolio: ${portfolio_value:.2f}"
    )
}
```

---

## Latency Targets

```
Data ingestion:    <100ms
Signal generation: <200ms  
Order execution:   <500ms ← main bottleneck
End-to-end:        <1000ms
```

## Common Pitfalls

```
❌ Using asyncio.gather for sequential trades
   → Use sequential await for order safety

❌ Storing secrets in code
   → Always use .env

❌ Full Kelly sizing
   → Always α = 0.25

❌ No timeout on API calls
   → Always ClientTimeout(total=10)

❌ JSON file for state
   → Use SQLite minimum, PostgreSQL production

❌ Tight coupling signal + execution
   → Always separate via event/queue

❌ Push more than 5 files at once
   → Batch max 5 files per commit
```

---

## File Structure (UPDATED — NO LEGACY)
```
projects/polymarket/polyquantbot/
├── core/
├── data/
├── strategy/
├── intelligence/
├── risk/
├── execution/
├── monitoring/
├── api/
├── infra/
├── backtest/
├── reports/
```
---

## SYSTEM RULES (CRITICAL)
```
- NO phase folders
- NO backward compatibility
- NO legacy structure
- Always use domain-based architecture
```
---

## PUSH RULES
```
- Max 5 files per batch
- Branch: feature/forge/[task-name]
- Commit incrementally
```
