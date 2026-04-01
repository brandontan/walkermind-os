# PolyQuantBot — System Architecture

**Version:** 1.0.0 (Domain-Based Refactor)  
**Date:** 2026-04-01  
**Author:** FORGE-X

---

## Folder Structure

```
projects/polymarket/polyquantbot/
├── core/                    # Core system utilities and pipeline orchestration
│   ├── pipeline/            # Pipeline runner, controllers, executors
│   ├── exceptions.py        # Custom exception types
│   ├── prelive_validator.py # Pre-live gate (8 safety checks)
│   ├── system_state.py      # System state management
│   └── startup_live_checks.py
│
├── infra/                   # Infrastructure configuration
│
├── data/                    # Data layer — market data ingestion
│   ├── websocket/           # WebSocket client for live market data
│   ├── orderbook/           # Order book management and snapshots
│   └── ingestion/           # Analytics, latency tracking, trade flow
│
├── strategy/                # Strategy layer — signal generation
│   ├── base/                # Base strategy interface + SignalEngine
│   ├── implementations/     # Concrete strategy implementations
│   └── features/            # Feature engineering
│
├── backtest/                # Backtesting engine (placeholder)
│
├── intelligence/            # Intelligence layer — ML/Bayesian
│   ├── pass_through.py      # Current: pass-through stub
│   ├── models/              # ML model inference
│   ├── bayesian/            # Bayesian prior updates
│   └── drift/               # Market drift detection
│
├── risk/                    # Risk management layer
│   ├── risk_guard.py        # Risk enforcement (drawdown, position limits)
│   ├── order_guard.py       # Order deduplication and validation
│   ├── health_monitor.py    # System health monitoring
│   ├── position_tracker.py  # Position state tracking
│   ├── fill_monitor.py      # Fill event tracking
│   └── exit_monitor.py      # Exit event monitoring
│
├── execution/               # Execution layer
│   ├── live_executor.py     # Live order execution (gated)
│   ├── simulator.py         # Paper trading simulation
│   ├── fill_tracker.py      # Fill reconciliation
│   └── reconciliation.py    # Trade reconciliation
│
├── monitoring/              # Observability layer
│   ├── signal_metrics.py    # Signal counter metrics
│   ├── activity_monitor.py  # Inactivity alerts
│   ├── live_audit.py        # Live trading audit log
│   ├── live_trade_logger.py # Trade event logging
│   ├── metrics_exporter.py  # Metrics export/persistence
│   ├── metrics_validator.py # Metrics validation
│   ├── schema.py            # Data schema definitions
│   ├── server.py            # Metrics webhook server
│   └── startup_checks.py   # System startup validation
│
├── api/                     # External API integrations
│   └── telegram_webhook.py  # Telegram webhook endpoint
│
├── telegram/                # Telegram notification system
│   ├── message_formatter.py # Centralized message formatting
│   ├── command_handler.py   # Bot command processing
│   ├── command_router.py    # Command routing
│   └── telegram_live.py     # Live trade notifications
│
├── config/                  # Runtime configuration
├── connectors/              # Exchange connectors (Kalshi, etc.)
│
└── reports/                 # Agent reports
    ├── forge/               # FORGE-X build reports
    ├── sentinel/            # SENTINEL validation reports
    └── briefer/             # BRIEFER prompt reports
```

## Data Flow

```
WebSocket (data/websocket/)
    ↓ market tick
OrderBook (data/orderbook/)
    ↓ snapshot/delta
Strategy (strategy/base/ + strategy/implementations/)
    ↓ Signal | None
Intelligence (intelligence/)
    ↓ IntelligenceContext (confidence-adjusted signal)
Risk (risk/)
    ↓ approved | blocked
Execution (execution/)
    ↓ order result
Monitoring (monitoring/)
    ↓ metrics, logs, alerts
Telegram (telegram/)
    ↓ notifications
```

## Layer Responsibilities

| Layer | Responsibility | Key Files |
|-------|---------------|-----------|
| **data** | Market data ingestion, WS connection, orderbook state | ws_client.py, orderbook.py |
| **strategy** | Signal generation, edge calculation | base_strategy.py, signal_engine.py |
| **intelligence** | Signal confidence adjustment, ML/Bayesian (future) | pass_through.py |
| **risk** | Position limits, drawdown guard, order dedup | risk_guard.py, order_guard.py |
| **execution** | Order placement, simulation, fill tracking | live_executor.py, simulator.py |
| **monitoring** | Metrics, audit logs, health checks | metrics_exporter.py, live_audit.py |
| **telegram** | Notifications, bot commands, alerts | telegram_live.py, command_handler.py |
| **core/pipeline** | Orchestration, go-live control, run lifecycle | pipeline_runner.py, run_controller.py |

## Risk Rules (Enforced)

- Max position: 10% of bankroll
- Daily loss limit: -$2,000
- Max drawdown 8% → stop all trades
- Kelly fraction: α = 0.25 (never full Kelly)
- Order deduplication required (OrderGuard)
- Interrupt switch in every execution path

## Latency Targets

| Stage | Target |
|-------|--------|
| Data ingestion | < 100ms |
| Signal generation | < 200ms |
| Order execution | < 500ms |
| End-to-end | < 1000ms |
