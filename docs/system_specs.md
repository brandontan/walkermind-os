# System Specifications
> AI Trading Team — Technical Reference
> Repo: https://github.com/bayuewalker/walker-ai-team
> File: /docs/system_specs.md

---

## 1. PLATFORM SPECIFICATIONS

### Polymarket (Primary)
```
Type:         CLOB Prediction Market
Network:      Polygon PoS
API:          CLOB API + Gamma API
WebSocket:    Real-time order book
Auth:         API Key + Polygon wallet
Token:        USDC (6 decimals)
Contract:     CTF (Conditional Token Framework)
Min order:    $1 USDC
Fee:          ~2% taker / 0% maker
```

### Kalshi (Secondary — Arb Target)
```
Type:         Regulated prediction market
Network:      Centralized (US regulated)
API:          REST API + WebSocket
Auth:         API Key
Currency:     USD cents
Use case:     Cross-platform arb vs Polymarket
```

### Binance (CEX Reference)
```
Use case:     Price reference for CEX lag exploit
WebSocket:    wss://stream.binance.com:9443
Streams:      bookTicker, aggTrade, kline
Lag exploit:  Polymarket lags Binance ~500ms
              on BTC/ETH major moves
```

### TradingView
```
Language:     Pine Script v5
Alerts:       Webhook → CONNECT pipeline
Webhook URL:  Set in alert → goes to CONNECT
Data:         Charts, backtesting, indicators
```

### MT4 / MT5
```
MT4 Language: MQL4 → .ex4 files
MT5 Language: MQL5 → .ex5 files
Bridge:       TradingView webhook → MT4/5 via CONNECT
EA Location:  Experts/Advisors folder
Indicator:    Indicators folder
```

---

## 2. TECH STACK DETAILS

### Core Bot Engine
```python
Language:    Python 3.11+
Async:       asyncio + aiohttp
WebSocket:   websockets library
HTTP:        aiohttp.ClientSession
Queue:       asyncio.Queue (event bus)
Typing:      Full type hints required
```

### Database Layer
```
PostgreSQL:  Trade history, positions, audit log
Redis:       Real-time cache, dedup store
             TTL: 24h for order dedup keys
InfluxDB:    Time-series price data
             Retention: 90 days
```

### Blockchain
```
Network:     Polygon PoS (Mainnet)
Chain ID:    137
RPC:         https://polygon-rpc.com
Gas:         EIP-1559 (maxFeePerGas)
Wallet:      Private key in .env (NEVER hardcode)
USDC:        0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
```

### Infrastructure
```
Dev:         Replit (mobile-accessible)
Production:  Replit always-on / VPS
Secrets:     .env file (never in code)
Logs:        Structured JSON logs
Monitoring:  Telegram alerts via CONNECT
```

---

## 3. BOT ARCHITECTURE — DATA FLOW

```
┌─────────────────────────────────────────┐
│           TRADING BOT                   │
│                                         │
│  LAYER 0 — DATA INGESTION               │
│  Polymarket WS + Binance WS +           │
│  Kalshi API + Chainlink Oracle          │
│  → asyncio.Queue (Event Bus)            │
│                                         │
│  LAYER 1 — RESEARCH                     │
│  ORACLE pipeline                        │
│  → news_fetcher + sentiment +           │
│    drift_detector                       │
│  → structured JSON output               │
│                                         │
│  LAYER 2 — SIGNAL GENERATION            │
│  QUANT engine                           │
│  → EV calculation                       │
│  → Bayesian update                      │
│  → Signal: YES/NO + size                │
│                                         │
│  LAYER 3 — RISK GATE                    │
│  SENTINEL check (hard gate)             │
│  → All checks must PASS                 │
│  → REJECT = order never sent            │
│                                         │
│  LAYER 4 — EXECUTION                    │
│  FORGE-X order manager                  │
│  → Dedup check                          │
│  → CLOB order submission                │
│  → Fill monitor                         │
│                                         │
│  LAYER 5 — ANALYTICS                    │
│  EVALUATOR logging                      │
│  → Trade logged to PostgreSQL           │
│  → Metrics updated                      │
│  → Daily report generated              │
└─────────────────────────────────────────┘
```

---

## 4. API SPECIFICATIONS

### Polymarket CLOB API
```
Base URL:    https://clob.polymarket.com
Auth:        L1 (wallet sig) or L2 (API key)

Key endpoints:
GET  /markets              — list markets
GET  /markets/{id}         — market detail
GET  /order-book/{id}      — order book
POST /order                — place order
DELETE /order/{id}         — cancel order
GET  /positions            — open positions
GET  /trades               — trade history

WebSocket:
wss://ws-subscriptions.polymarket.com
Subscribe: {"type":"subscribe","channel":"live_activity"}
```

### Polymarket Gamma API
```
Base URL:    https://gamma-api.polymarket.com
Use:         Market data, search, metadata
GET /markets — searchable market list
GET /events  — upcoming events
```

### Rate Limits
```
Polymarket:  10 req/sec (REST)
             Unlimited (WebSocket)
Binance:     1200 req/min (REST)
             Unlimited (WebSocket)
Kalshi:      100 req/min
```

---

## 5. FILE STRUCTURE

```
trading-ai-team/
│
├── strategy/
│   ├── signals.py          # signal generation
│   ├── sizing.py           # Kelly + position sizing
│   ├── backtest.py         # backtesting engine
│   ├── config.yaml         # ALL parameters here
│   └── oracle/
│       ├── news_fetcher.py
│       ├── sentiment.py
│       ├── drift_detector.py
│       ├── data_schema.py
│       └── oracle_pipeline.py
│
├── engine/
│   ├── core/
│   │   ├── order_manager.py    # OMS + dedup
│   │   ├── execution.py        # CLOB submission
│   │   └── event_bus.py        # asyncio queue
│   ├── api/
│   │   ├── polymarket.py       # Polymarket connector
│   │   ├── kalshi.py           # Kalshi connector
│   │   └── binance.py          # Binance WebSocket
│   ├── db/
│   │   ├── postgres.py         # trade history
│   │   ├── redis_client.py     # dedup + cache
│   │   └── models.py           # data models
│   └── utils/
│       ├── logger.py           # structured logging
│       ├── retry.py            # retry decorator
│       └── validators.py       # input validation
│
├── risk/
│   ├── sentinel.py         # main risk gate
│   ├── rules.yaml          # risk parameters
│   ├── kill_switch.py      # emergency stop
│   └── audit_log.py        # immutable log
│
├── strategy/scout/
│   ├── arb_scanner.py      # background scanner
│   ├── fee_calculator.py   # platform fees
│   └── opportunity_log.py  # all detections
│
├── analytics/
│   ├── metrics.py          # all calculations
│   ├── evaluator.py        # evaluation engine
│   ├── report_generator.py # auto reports
│   └── reports/            # YYYY-MM-DD.md
│
├── indicators/
│   ├── pinescript/         # .pine files
│   ├── mql4/               # MT4 files
│   └── mql5/               # MT5 files
│
├── frontend/
│   └── src/
│       ├── components/
│       ├── pages/
│       ├── hooks/
│       └── services/
│
├── integrations/
│   ├── webhooks/           # incoming webhooks
│   ├── brokers/            # broker connectors
│   ├── alerts/             # Telegram bot
│   └── deploy/             # deployment scripts
│
├── docs/
│   ├── PROJECT_STATE.md    # current state
│   ├── formulas.md         # this file
│   └── system_specs.md     # technical specs
│
├── .env.example            # ALL env vars listed
├── requirements.txt        # Python dependencies
└── README.md
```

---

## 6. ENVIRONMENT VARIABLES

```bash
# .env.example — ALL variables required

# Polymarket
POLYMARKET_API_KEY=
POLYMARKET_API_SECRET=
POLYMARKET_PRIVATE_KEY=      # Polygon wallet
POLYMARKET_PROXY_ADDRESS=    # L2 proxy contract

# Blockchain
POLYGON_RPC_URL=https://polygon-rpc.com
POLYGON_CHAIN_ID=137

# Kalshi
KALSHI_API_KEY=
KALSHI_API_SECRET=

# Binance
BINANCE_API_KEY=
BINANCE_API_SECRET=

# Database
POSTGRES_URL=
REDIS_URL=
INFLUX_URL=
INFLUX_TOKEN=

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Risk (can override rules.yaml)
MAX_POSITION_PCT=0.10
DAILY_LOSS_LIMIT=-2000
KELLY_FRACTION=0.25
```

---

## 7. ENGINEERING STANDARDS

### Code Requirements
```python
# Every module must have:
"""
Module: [name]
Purpose: [one line description]
Owner: [agent name]
Version: 1.0.0
"""

# Every function must have:
async def place_order(
    market_id: str,
    side: str,
    size: float,
    price: float
) -> dict:
    """
    Place order on Polymarket CLOB.
    
    Args:
        market_id: Polymarket market identifier
        side: 'YES' or 'NO'
        size: Order size in USDC
        price: Limit price (0.0 to 1.0)
    
    Returns:
        Order confirmation dict
        
    Raises:
        OrderRejectedError: If SENTINEL rejects
        APIError: If Polymarket API fails
    """
```

### Error Handling Standard
```python
# Every external call:
try:
    result = await api_call()
except asyncio.TimeoutError:
    logger.error("timeout", extra={"call": "api_name"})
    raise
except Exception as e:
    logger.error("unexpected", extra={"error": str(e)})
    raise
```

### Logging Standard
```python
import structlog
logger = structlog.get_logger()

# Every critical action:
logger.info("order_placed", extra={
    "market_id": market_id,
    "side": side,
    "size": size,
    "price": price,
    "sentinel_approved": True,
    "timestamp": datetime.utcnow().isoformat()
})
```

### Dedup Pattern
```python
# Before every order:
dedup_key = f"order:{market_id}:{side}:{price}:{size}"
if await redis.exists(dedup_key):
    raise DuplicateOrderError(f"Duplicate: {dedup_key}")
await redis.setex(dedup_key, 86400, "1")  # 24h TTL
```

---

## 8. DEPLOYMENT — REPLIT

```bash
# replit.nix or .replit config
run = "python main.py"

# main.py entry point
async def main():
    await asyncio.gather(
        data_ingestion_loop(),
        signal_engine_loop(),
        arb_scanner_loop(),      # SCOUT
        report_generator_loop(), # EVALUATOR
    )

asyncio.run(main())
```

### Keep-Alive (Replit)
```
Use Replit Always On (paid)
OR
UptimeRobot ping every 5 minutes
URL: your-replit-url.replit.app/health
```

---

*Reference: AI Trading Team System Architecture v1.0*
*Repo: https://github.com/bayuewalker/walker-ai-team*
