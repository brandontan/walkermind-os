# System Specifications
> AI Trading Team — Technical Reference (Phase 10.2 Aligned)
> Repo: https://github.com/bayuewalker/walker-ai-team
> File: /docs/system_specs.md

---

## 1. PLATFORM SPECIFICATIONS

### Polymarket (Primary)
Type: CLOB Prediction Market  
Network: Polygon PoS  
API: CLOB API + Gamma API  
WebSocket: Real-time order book  
Auth: API Key + Polygon wallet  
Token: USDC (6 decimals)  
Contract: CTF (Conditional Token Framework)  
Min order: $1  
Fee: ~2% taker / 0% maker  

---

### Kalshi (Secondary — Arb Target)
Type: Regulated prediction market  
API: REST + WebSocket  
Currency: USD cents  
Use: Cross-platform arbitrage signal (NO execution)

---

### Binance (Reference)
Use: Price reference (lag exploit)  
Lag: ~500ms vs Polymarket (BTC/ETH)

---

## 2. TECH STACK

Core:
- Python 3.11+
- asyncio (mandatory)
- aiohttp (HTTP)
- websockets (WS)
- asyncio.Queue (event bus)

Database:
- PostgreSQL (trades, audit)
- Redis (cache + dedup)
- InfluxDB (time-series)

Blockchain:
- Polygon PoS (chain 137)
- USDC contract
- Private key via .env only

---

## 3. SYSTEM ARCHITECTURE

### PIPELINE (MANDATORY)

DATA → SIGNAL → CONTROL → EXECUTION → MONITORING

---

### LAYER BREAKDOWN

#### LAYER 0 — DATA
- Polymarket WS (orderbook)
- Binance WS (reference)
- Kalshi API (arb)
- → Event Bus (asyncio.Queue)

---

#### LAYER 1 — SIGNAL
- QUANT Engine
- EV calculation
- Bayesian update
- Output: signal (side, size, price)

---

#### LAYER 2 — CONTROL (CRITICAL)

GoLiveController:
- metrics gating (EV, fill rate, latency, drawdown)
- block execution if thresholds fail

ExecutionGuard:
- liquidity check
- slippage check
- position limit
- dedup enforcement

CircuitBreaker:
- latency spike detection
- failure escalation
- auto HALT system

---

#### LAYER 3 — EXECUTION

OrderManager:
- order creation
- dedup signature (Redis)

Execution Engine:
- async CLOB submission

FillTracker:
- expected vs actual price
- slippage (bps)
- fill latency
- fill accuracy

Reconciliation:
- order ↔ fill matching
- partial fill aggregation
- duplicate detection
- ghost position prevention

---

#### LAYER 4 — MONITORING

MetricsValidator:
- EV capture
- fill rate
- latency
- slippage stats
- go_live_ready flag

Telegram Notifier:
- checkpoint reports (6h / 12h / 24h)
- error alerts
- kill alerts

System State:
- RUNNING
- PAUSED
- HALTED

---

## 4. SENTINEL (UPDATED ROLE)

SENTINEL is NOT part of runtime pipeline.

Purpose:
- Pre GO-LIVE validation
- Stress testing
- Failure simulation
- System audit

Output:
- Stability score
- Risk report
- GO-LIVE verdict

---

## 5. EXECUTION RULES

Latency Targets:
- ingest <100ms
- signal <200ms
- execution <500ms

Risk:
- Max position: 10% bankroll
- Max concurrent trades: 5
- Drawdown: 8% → HALT
- Daily loss: -$2000 → PAUSE

Slippage:
- reject if above threshold
- alert on spike

Dedup:
- required on every order (Redis TTL 24h)

---

## 6. API (POLYMARKET)

Base: https://clob.polymarket.com  

Endpoints:
GET /markets  
GET /order-book/{id}  
POST /order  
DELETE /order/{id}  
GET /positions  

WebSocket:
wss://ws-subscriptions.polymarket.com  

---

## 7. FILE STRUCTURE

projects/polymarket/polyquantbot/

execution/
- fill_tracker.py
- reconciliation.py
- simulator.py

phase10/
- go_live_controller.py
- execution_guard.py
- pipeline_runner.py
- arb_detector.py

phase9/
- metrics_validator.py
- telegram_live.py

phase8/
- risk_guard.py
- order_guard.py
- position_tracker.py

phase7/
- ws_client.py

---

## 8. ENV VARIABLES

POLYMARKET_API_KEY=  
POLYMARKET_API_SECRET=  
POLYMARKET_PRIVATE_KEY=  

POLYGON_RPC_URL=  

KALSHI_API_KEY=  

POSTGRES_URL=  
REDIS_URL=  
INFLUX_URL=  

TELEGRAM_TOKEN=  
TELEGRAM_CHAT_IDS=  

---

## 9. ENGINEERING STANDARDS

GLOBAL (MANDATORY):

- Python 3.11+
- asyncio only
- .env for secrets
- Idempotent operations
- Retry + timeout on all external calls
- Structured JSON logging
- Zero silent failure

Async Safety:
- protect shared state (locks if needed)
- avoid race condition
- deterministic async flow

---

## 10. DEPLOYMENT (UPDATED)

### Entry Point
python main.py

---

### Runtime Loop
- data ingestion loop
- signal engine loop
- execution pipeline
- monitoring + notifier

---

### DEPLOYMENT OPTIONS

#### 1. Replit (Dev / Light)
- mobile access
- quick testing
- not for heavy production

---

#### 2. VPS (RECOMMENDED)

Providers:
- Hetzner / DigitalOcean / AWS / GCP

Setup:
- Ubuntu 22.04+
- Python 3.11
- Redis + PostgreSQL

Process manager:
- systemd (recommended)

---

#### 3. Docker (Scalable)

- reproducible environment
- docker-compose setup

---

#### 4. Cloud (Advanced)

- AWS / GCP / Fly.io
- multi-region scaling

---

### PROCESS MANAGEMENT

- systemd OR pm2 OR supervisord
- auto restart required
- persistent logging required

---

### HEALTH CHECK

/health

{
  "status": "ok",
  "system": "RUNNING",
  "latency_ms": 120
}

---

### HARD RULES

- NEVER run without process manager
- ALWAYS enable restart on crash
- ALWAYS log all critical events
- ALWAYS monitor latency & errors

---

## 11. GO-LIVE MODES

PAPER:
- no real execution

LIVE:
- requires GoLiveController approval
- ExecutionGuard enforced

---

## 12. SYSTEM PRINCIPLES

- No execution without validation
- Risk > profit
- No silent failure
- Deterministic behavior
- Full observability

---

## 13. INFRA DIAGRAM

┌────────────────────────────────────────────────────────────┐
│                    WALKER AI SYSTEM                        │
└────────────────────────────────────────────────────────────┘
                ┌───────────────┐
                │   Binance WS   │
                │ (price ref)    │
                └──────┬────────┘
                       │
                ┌──────▼────────┐
                │ Polymarket WS │
                │ (orderbook)   │
                └──────┬────────┘
                       │
                ┌──────▼────────┐
                │ Kalshi API    │
                │ (arb signal)  │
                └──────┬────────┘
                       │
        ┌──────────────▼──────────────┐
        │      DATA INGESTION         │
        │ asyncio + WS + Event Bus    │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │       SIGNAL ENGINE         │
        │ EV + Bayesian + Edge calc   │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │        CONTROL LAYER        │
        │ ┌────────────────────────┐ │
        │ │ GoLiveController      │ │
        │ │ ExecutionGuard        │ │
        │ │ CircuitBreaker        │ │
        │ └────────────────────────┘ │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │        EXECUTION LAYER      │
        │ ┌────────────────────────┐ │
        │ │ OrderManager          │ │
        │ │ Execution Engine      │ │
        │ │ FillTracker           │ │
        │ │ Reconciliation        │ │
        │ └────────────────────────┘ │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │        MONITORING           │
        │ ┌────────────────────────┐ │
        │ │ MetricsValidator       │ │
        │ │ Telegram Notifier      │ │
        │ │ System State           │ │
        │ └────────────────────────┘ │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │        DATABASE LAYER       │
        │ PostgreSQL / Redis / Influx│
        └─────────────────────────────┘

---

## 14. FILE STRUCTURE

projects/polymarket/polyquantbot/

├── main.py                        # entry point

├── core/                          # core system
│   ├── event_bus.py
│   ├── config.py
│   └── system_state.py

├── data/                          # ingestion layer
│   ├── ws_client.py               # Polymarket WS
│   ├── binance_ws.py
│   ├── kalshi_client.py
│   └── market_cache.py

├── signal/                        # strategy layer
│   ├── engine.py                  # main signal logic
│   ├── ev.py
│   ├── bayesian.py
│   └── models.py

├── control/                       # control layer (CRITICAL)
│   ├── go_live_controller.py
│   ├── execution_guard.py
│   ├── circuit_breaker.py
│   └── rules.py

├── execution/                     # execution layer
│   ├── order_manager.py
│   ├── engine.py
│   ├── simulator.py
│   ├── fill_tracker.py
│   └── reconciliation.py

├── monitoring/                    # monitoring layer
│   ├── metrics_validator.py
│   ├── telegram_notifier.py
│   ├── scheduler.py
│   └── health.py

├── risk/                          # risk system
│   ├── risk_guard.py
│   ├── order_guard.py
│   ├── position_tracker.py
│   └── kill_switch.py

├── strategy/                      # future (Phase 11)
│   ├── router.py
│   ├── weighting.py
│   └── performance.py

├── connectors/                    # external APIs
│   ├── polymarket.py
│   ├── kalshi.py
│   └── binance.py

├── storage/                       # database layer
│   ├── postgres.py
│   ├── redis_client.py
│   ├── influx.py
│   └── models.py

├── utils/
│   ├── logger.py
│   ├── retry.py
│   ├── time.py
│   └── validators.py

├── tests/
│   ├── phase9/
│   ├── phase10/
│   ├── phase101/
│   └── phase102/

├── report/
│   ├── PHASE10_COMPLETE.md
│   ├── PHASE10.2_COMPLETE.md
│   └── SENTINEL_REPORT.md

├── .env
├── requirements.txt
└── README.md

---

*System Spec v2.0 — Phase 10.2 Aligned*
*Walker AI Trading Team*
