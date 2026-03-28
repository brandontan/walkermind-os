<div align="center">

```
██╗    ██╗ █████╗ ██╗     ██╗  ██╗███████╗██████╗
██║    ██║██╔══██╗██║     ██║ ██╔╝██╔════╝██╔══██╗
██║ █╗ ██║███████║██║     █████╔╝ █████╗  ██████╔╝
██║███╗██║██╔══██║██║     ██╔═██╗ ██╔══╝  ██╔══██╗
╚███╔███╔╝██║  ██║███████╗██║  ██╗███████╗██║  ██║
 ╚══╝╚══╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
        AI  T R A D I N G  T E A M
```

**Multi-Agent AI System for Algorithmic Trading**

*Polymarket · TradingView · MT4/MT5 · Kalshi*

---

![Status](https://img.shields.io/badge/Status-Building-gold?style=for-the-badge&logo=github)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Polymarket](https://img.shields.io/badge/Polymarket-CLOB-00C851?style=for-the-badge)
![Private](https://img.shields.io/badge/Repo-Private-red?style=for-the-badge&logo=github)

</div>

---

## ◆ Overview

**Walker AI Trading Team** is a fully autonomous multi-agent AI system designed to build, deploy, and maintain algorithmic trading bots, indicators, and tools across prediction markets and traditional trading platforms.

> 11 specialized AI agents. One mission: build systems that trade profitably while you sleep.

---

## ◆ Architecture

```
                        ┌─────────────┐
                        │   COMMAND   │  ← You give orders here
                        │  Supervisor │
                        └──────┬──────┘
                               │
           ┌───────────────────┼───────────────────┐
           │                   │                   │
    ┌──────▼──────┐    ┌───────▼──────┐   ┌───────▼──────┐
    │  STRATEGY   │    │   BUILDER    │   │   GUARDIAN   │
    │  DIVISION   │    │   DIVISION   │   │   DIVISION   │
    └──────┬──────┘    └───────┬──────┘   └───────┬──────┘
           │                   │                   │
    ┌──────┴──────┐    ┌───────┴──────┐   ┌───────┴──────┐
    │ QUANT       │    │ FORGE-X      │   │ SENTINEL     │
    │ ORACLE      │    │ PIXEL        │   │ SCOUT        │
    └─────────────┘    │ CANVAS       │   │ EVALUATOR    │
                       │ CONNECT      │   └─────────────-┘
                       └─────────────┘
                               │
                        ┌──────▼──────┐
                        │   BRIEFER   │ → External AI
                        └─────────────┘
```

---

## ◆ The Team — 11 Agents

| Agent | Division | Role |
|-------|----------|------|
| 👑 **COMMAND** | Supervisor | Orchestrates team, manages workflow, asks approval before every action |
| 📊 **QUANT** | Strategy | Writes signal logic, position sizing (Kelly), backtesting code |
| 🔮 **ORACLE** | Strategy | Writes data fetchers, sentiment parsers, drift detectors |
| ⚙️ **FORGE-X** | Builder | Core Python engine, Polymarket CLOB API, async infrastructure |
| 📈 **PIXEL** | Builder | Pine Script v5 indicators, MQL4/5 Expert Advisors |
| 🎨 **CANVAS** | Builder | Trading dashboards, real-time UI, TradingView charts |
| 🔗 **CONNECT** | Builder | Platform bridges, webhooks, Telegram alerts, deployment |
| 🛡️ **SENTINEL** | Guardian | Writes risk engine code — hard gate before every order |
| 🔍 **SCOUT** | Guardian | Writes arb scanner — detects cross-platform price gaps |
| 📋 **EVALUATOR** | Guardian | Writes performance metrics & auto-reporting engine |
| 📝 **BRIEFER** | External | Compresses project context into prompts for external AI |

---

## ◆ Platforms

```
PREDICTION MARKETS          CHARTING & EXECUTION
─────────────────          ────────────────────
● Polymarket (Primary)      ● TradingView (Pine Script v5)
● Kalshi (Arb Target)       ● MT4 (MQL4 Expert Advisors)
                            ● MT5 (MQL5 Expert Advisors)

DATA SOURCES                INFRASTRUCTURE
────────────                ──────────────
● Binance WebSocket         ● Python 3.11+ asyncio
● Chainlink Oracle          ● PostgreSQL + Redis
● Polygon PoS               ● Polygon PoS blockchain
● Polymarket CLOB API       ● Replit (deployment)
```

---

## ◆ Project Structure

```
walker-ai-team/
│
├── 📄 CLAUDE.md               # AI memory — read every session
├── 📄 PROJECT_STATE.md        # Current build status
│
├── 📁 docs/
│   ├── formulas.md            # Core trading formulas
│   └── system_specs.md        # Technical specifications
│
└── 📁 projects/
    ├── polymarket/             # → FORGE-X
    │   ├── src/
    │   │   └── main.py
    │   ├── .env.example
    │   └── requirements.txt
    │
    ├── tradingview/
    │   ├── indicators/         # → PIXEL
    │   └── strategies/         # → PIXEL
    │
    └── mt5/
        ├── ea/                 # → PIXEL
        └── indicators/         # → PIXEL
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
# These rules are NON-NEGOTIABLE
# SENTINEL enforces them in code before every order

MAX_POSITION_PCT      = 0.10   # 10% bankroll per trade
MAX_CONCURRENT        = 5      # positions at once
DAILY_LOSS_LIMIT      = -2000  # USD — pause if hit
MAX_DRAWDOWN          = 0.08   # 8% → stop all trades
KELLY_FRACTION        = 0.25   # NEVER full Kelly
MIN_LIQUIDITY         = 10000  # USD market depth
MIN_EV                = 0.0    # positive EV required

# ⚠️ NEVER use full Kelly on 5-min markets!
```

---

## ◆ Core Formulas

```
EDGE DETECTION          POSITION SIZING         PERFORMANCE
──────────────          ───────────────         ───────────
EV = p·b − (1−p)        f = (p·b−q) / b         SR = (ER−RF) / σ(R)
edge = p_model−p_mkt    f_final = 0.25 × f      PF = profit / loss
S = (p_model−p_mkt)/σ   VAR = μ − 1.645·σ       MDD = (P−T) / P
M = Pt − Pt-n           CVaR = E[loss|loss>VaR]  WR = wins / total
```

---

## ◆ How It Works

```
1. FOUNDER gives order to COMMAND
        ↓
2. COMMAND analyzes → suggests → asks approval
        ↓
3. Founder approves
        ↓
4. COMMAND delegates to specialist agents
        ↓
5. Agents BUILD → TEST → DEPLOY
        ↓
6. Bot runs 24/7 on server automatically
        ↓
7. Team enters STANDBY — waits for next order
```

---

## ◆ Team Operational Modes

```
🔨 BUILD MODE      Active when order received
                   Agents working on program

⏸️ STANDBY MODE   After successful deployment
                   Bot runs, team is idle
                   Waiting for next order

🔧 MAINTENANCE     When bug/issue reported
                   Fix → test → redeploy
```

---

## ◆ Branch Convention

```bash
feature/[agent]/[task-name]

# Examples:
feature/forge/websocket-connection
feature/quant/momentum-strategy
feature/pixel/rsi-indicator
feature/sentinel/drawdown-rules
feature/scout/polymarket-kalshi-arb
```

---

## ◆ Knowledge Base

| File | Contents | Used By |
|------|----------|---------|
| `PROJECT_STATE.md` | Current build status | All agents |
| `docs/formulas.md` | Trading formulas | QUANT, SENTINEL, EVALUATOR |
| `docs/system_specs.md` | Tech specs & API docs | FORGE-X, CONNECT |
| `CLAUDE.md` | AI coding memory | Claude Code |

---

<div align="center">

---

```
WALKER AI TRADING TEAM
Build. Deploy. Profit. Repeat.
```

*Private Repository — Bayue Walker © 2026*

</div>
