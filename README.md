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
| 👑 **COMMANDER** | Claude Project | Master AI — combines ALL domain expertise. Receives all orders, plans, advises, generates tasks. Never starts without founder approval. |
| ⚙️ **FORGE-X** | Claude Code | Full-stack engineer — builds everything. Python, Pine Script, MQL4/5, React. Reads GitHub directly. Builds until deployed & running. |
| 📝 **BRIEFER** | Claude Project | Prompt maker — called only when team needs help from external AI (ChatGPT, Gemini, Grok, etc). |

---

## ◆ COMMANDER — Combined Expertise

COMMANDER masters all specialist domains in one agent:

```
📊 Quantitative Trading    — signals, Kelly sizing, backtesting
🔮 Market Intelligence     — sentiment, news flow, drift detection
🛡️ Risk Management         — drawdown rules, kill switch, VAR
🔍 Arbitrage Detection     — cross-platform arb, CEX lag exploit
📋 Performance Analysis    — Sharpe, Sortino, win rate, reporting
📈 Pine Script v5          — TradingView indicators & strategies
⚙️ MQL4/5                  — MT4/MT5 Expert Advisors
🔨 Backend Engineering     — Python asyncio, CLOB API, WebSocket
🎨 Frontend & Dashboards   — React, real-time P&L UI
🔗 Integrations            — webhooks, Telegram alerts, pipelines
```

---

## ◆ How It Works

```
FOUNDER gives order
        ↓
COMMANDER analyzes → advises → asks approval
        ↓
Founder approves
        ↓
COMMANDER generates detailed task for FORGE-X
        ↓
FORGE-X builds directly in GitHub repo
        ↓
Bot deployed → running 24/7 on server ✅
        ↓
Team STANDBY — waiting for next order

─────────────────────────────────────────
BRIEFER called only when external AI needed
→ Compresses context → generates prompt
→ Forward to ChatGPT / Gemini / Grok
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
├── 📄 CLAUDE.md               # FORGE-X memory (read every session)
├── 📄 PROJECT_STATE.md        # Current build status
│
├── 📁 docs/
│   ├── KNOWLEDGE_BASE.md      # Master knowledge reference
│   ├── formulas.md            # Core trading formulas
│   ├── system_specs.md        # Technical specifications
│   ├── prediction_market_api_context.md
│   ├── pico.pdf               # PICO framework (small-budget)
│   └── advancee_trade_strategy.pdf  # 151 trading strategies
│
└── 📁 projects/
    ├── polymarket/             # Python trading bot → FORGE-X
    ├── tradingview/
    │   ├── indicators/         # Pine Script v5 → FORGE-X
    │   └── strategies/         # Pine Script v5 → FORGE-X
    └── mt5/
        ├── ea/                 # MQL5 Expert Advisors → FORGE-X
        └── indicators/         # MQL5 indicators → FORGE-X
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
# Non-negotiable — enforced in code before every order

MAX_POSITION_PCT   = 0.10   # 10% bankroll per trade
MAX_CONCURRENT     = 5      # max positions at once
DAILY_LOSS_LIMIT   = -2000  # USD — pause trading if hit
MAX_DRAWDOWN       = 0.08   # 8% → stop all trades immediately
KELLY_FRACTION     = 0.25   # NEVER full Kelly
MIN_LIQUIDITY      = 10000  # USD minimum market depth
MIN_EV             = 0.0    # positive expected value required

# ⚠️ NEVER use full Kelly — especially on 5-min markets!
# ⚠️ Always use Fractional Kelly: f_final = 0.25 × f_kelly
```

---

## ◆ Core Formulas

```
EDGE DETECTION              POSITION SIZING
──────────────              ───────────────
EV = p·b − (1−p)            f = (p·b − q) / b
edge = p_model − p_mkt      f_final = 0.25 × f  ← always
S = (p_model − p_mkt) / σ   VAR = μ − 1.645·σ
M = Pt − Pt-n               MDD = (Peak−Trough)/Peak

PERFORMANCE                 ARBITRAGE
───────────                 ─────────
SR = (ER−RF) / σ(R)         net_edge = gross − fees − slip
PF = gross_profit / loss    CEX lag = ~500ms (BTC/ETH)
WR = wins / total           min net_edge > 2% to execute
```

---

## ◆ Build Roadmap

```
Phase 1 — Foundation    Setup, repo, API connections
Phase 2 — Strategy      Signals, sizing, backtest
Phase 3 — Intelligence  Engine, risk gate, arb scanner
Phase 4 — Production    Deploy, dashboard, confirm ✅ → STANDBY
```

---

## ◆ Operational Modes

```
🔨 BUILD MODE      Active when order received
                   COMMANDER plans → FORGE-X builds

⏸️ STANDBY         Bot runs 24/7 automatically
                   Team idle — zero self-initiative

🔧 MAINTENANCE     Bug/issue reported by founder
                   Fix → test → redeploy → confirm
```

---

## ◆ Branch Convention

```bash
feature/forge/[task-name]

# Examples:
feature/forge/polymarket-websocket
feature/forge/momentum-signal
feature/forge/pine-rsi-indicator
feature/forge/mt5-momentum-ea
feature/forge/sentinel-risk-engine
feature/forge/arb-scanner
```

---

## ◆ Knowledge Base

| File | Contents | Used By |
|------|----------|---------|
| `PROJECT_STATE.md` | Current build status | COMMANDER |
| `docs/KNOWLEDGE_BASE.md` | All core knowledge in one file | COMMANDER |
| `docs/advancee_trade_strategy.pdf` | 151 strategies + 550 formulas | COMMANDER |
| `docs/pico.pdf` | PICO small-budget framework | COMMANDER |
| `CLAUDE.md` | Project memory for Claude Code | FORGE-X |

---

<div align="center">

---

```
WALKER AI TRADING TEAM
Build. Deploy. Profit. Repeat.
```

*Private Repository — Bayue Walker © 2026*

</div>
