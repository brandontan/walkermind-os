<div align="center">

```
██╗    ██╗ █████╗ ██╗     ██╗  ██╗███████╗██████╗
██║    ██║██╔══██╗██║     ██║ ██╔╝██╔════╝██╔══██╗
██║ █╗ ██║███████║██║     █████╔╝ █████╗  ██████╔╝
██║███╗██║██╔══██║██║     ██╔═██╗ ██╔══██╗██╔══██╗
╚███╔███╔╝██║  ██║███████╗██║  ██╗███████╗██║  ██║
 ╚══╝╚══╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
            AI  T R A D I N G  T E A M
```

**Multi-Agent AI System for Algorithmic Trading**

*Polymarket · TradingView · MT4/MT5 · Kalshi*

---

![Status](https://img.shields.io/badge/Status-Building-gold?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Polymarket](https://img.shields.io/badge/Polymarket-CLOB-00C851?style=for-the-badge)
![Private](https://img.shields.io/badge/Repo-Private-red?style=for-the-badge&logo=github)

</div>

---

## ◆ Overview

**Walker AI Trading Team** is a fully autonomous AI system that builds, deploys, and maintains algorithmic trading bots, indicators, and tools across prediction markets and traditional platforms.

> 3 specialized AI agents. One mission: build systems that trade profitably while you sleep.

---

## ◆ AI Team — 3 Agents

| Agent | Platform | Role |
|-------|----------|------|
| 👑 **COMMANDER** | Claude Project | Master AI — combines all domain expertise. Receives all orders, plans, advises, generates tasks. Never starts without founder approval. |
| ⚙️ **FORGE-X** | Claude Code | Full-stack engineer — builds everything. Python, Pine Script, MQL4/5, React. Reads GitHub directly. Builds until deployed. |
| 📝 **BRIEFER** | Claude Project | Prompt maker — compresses project context and generates ready-to-send prompts for external AI when needed. |

---

## ◆ How It Works

```
FOUNDER gives order
        ↓
COMMANDER analyzes → advises → asks approval
        ↓
Founder approves
        ↓
COMMANDER generates task for FORGE-X
        ↓
FORGE-X builds directly in GitHub
        ↓
Bot deployed → running 24/7 on server ✅
        ↓
Team STANDBY — waiting for next order
```

---

## ◆ Platforms

```
PREDICTION MARKETS        CHARTING & EXECUTION
──────────────────        ────────────────────
● Polymarket (Primary)    ● TradingView (Pine Script v5)
● Kalshi (Arb Target)     ● MT4 (MQL4 Expert Advisors)
                          ● MT5 (MQL5 Expert Advisors)

DATA SOURCES              INFRASTRUCTURE
────────────              ──────────────
● Binance WebSocket       ● Python 3.11+ asyncio
● Chainlink Oracle        ● PostgreSQL + Redis
● PM Intelligence API     ● Polygon PoS blockchain
● Social Pulse (X/Twitter)● Replit deployment
```

---

## ◆ Project Structure

```
walker-ai-team/
│
├── 📄 CLAUDE.md               # FORGE-X memory
├── 📄 PROJECT_STATE.md        # Current build status
│
├── 📁 docs/
│   ├── KNOWLEDGE_BASE.md      # Master knowledge reference
│   ├── formulas.md            # Core trading formulas
│   ├── system_specs.md        # Technical specifications
│   ├── prediction_market_api_context.md
│   ├── pico.pdf               # PICO framework
│   └── advancee_trade_strategy.pdf  # 151 strategies
│
└── 📁 projects/
    ├── polymarket/             # Python trading bot
    ├── tradingview/
    │   ├── indicators/         # Pine Script v5
    │   └── strategies/         # Pine Script v5
    └── mt5/
        ├── ea/                 # MQL5 Expert Advisors
        └── indicators/         # MQL5 indicators
```

---

## ◆ Performance Targets

| Metric | Target |
|--------|--------|
| Win Rate | > 70% |
| Sharpe Ratio | > 2.5 |
| Max Drawdown | < 5% |
| Profit Factor | > 1.5 |
| Avg Profit/Trade | > $15 |
| End-to-End Latency | < 1000ms |

---

## ◆ Risk Rules

```python
MAX_POSITION_PCT   = 0.10   # 10% bankroll per trade
MAX_CONCURRENT     = 5      # positions at once
DAILY_LOSS_LIMIT   = -2000  # USD — pause if hit
MAX_DRAWDOWN       = 0.08   # 8% → stop all trades
KELLY_FRACTION     = 0.25   # NEVER full Kelly
MIN_LIQUIDITY      = 10000  # USD market depth
# ⚠️ NEVER full Kelly on 5-min markets!
```

---

## ◆ Build Roadmap

```
Phase 1 — Foundation     Setup, repo, API connections
Phase 2 — Strategy       Signals, sizing, backtest
Phase 3 — Intelligence   Engine, risk, scanner
Phase 4 — Production     Deploy, dashboard ✅ → STANDBY
```

---

## ◆ Operational Modes

```
🔨 BUILD MODE    Active when order received
⏸️ STANDBY      Bot runs 24/7, team idle
🔧 MAINTENANCE   Fix → test → redeploy
```

---

## ◆ Branch Convention

```
feature/forge/[task-name]

# Examples:
feature/forge/polymarket-websocket
feature/forge/momentum-signal
feature/forge/pine-rsi-indicator
feature/forge/mt5-momentum-ea
```

---

<div align="center">

```
█▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀█
█        WALKER AI TRADING TEAM                 █
█     Build. Deploy. Profit. Repeat.            █
█  Private Repository — Bayue Walker © 2026     █
█▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄█
```

</div>
