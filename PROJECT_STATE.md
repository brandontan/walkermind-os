# PROJECT STATE — AI Trading Team
> Owner: Bayue Walker
> Last Updated: [UPDATE THIS DATE EVERY SESSION]
> Status: 🔧 SETUP PHASE

---

## 👤 FOUNDER
- Name: Bayue Walker
- Access: Smartphone only (Android)
- Primary AI: Claude Projects (11 agents)
- Secondary AI: Gemini Gems (backup + mobile)
- Dev Environment: Replit (mobile-accessible)
- Version Control: GitHub (GitHub Mobile app)

---

## 🎯 PROJECT MISSION
Build an AI-powered trading system consisting of:
- Automated trading bots
- Custom indicators
- Expert Advisors (EA)
- Trading tools & dashboards

Across multiple platforms, running 24/7 on server.
Team builds until program runs well → STANDBY → wait for next order.

---

## 🏗️ SYSTEM ARCHITECTURE

### Primary Platform
- **Polymarket** — CLOB prediction markets (primary focus)

### Secondary Platforms
- **Kalshi** — prediction markets (arb target)
- **TradingView** — charting, Pine Script indicators & strategies
- **MT4 / MT5** — Expert Advisors & custom indicators
- **Binance / crypto** — data source & CEX price reference

### Tech Stack
```
Language:    Python 3.11+ (asyncio, aiohttp, websockets)
Scripting:   Pine Script v5 (TradingView)
EA Language: MQL4 (MT4) / MQL5 (MT5)
Frontend:    React + TypeScript / HTML CSS JS
Database:    PostgreSQL + Redis + InfluxDB (time-series)
Blockchain:  Polygon PoS, EIP-1559, CTF contracts
Deployment:  Replit / VPS server
Version Ctrl: GitHub (branch-based per agent)
```

---

## 👥 AI TRADING TEAM — 11 AGENTS

### 🏛️ SUPERVISOR
| Agent | Role | Claude Project |
|-------|------|---------------|
| **COMMAND** | Supervisor — orchestrates all agents | ✅ Created |

### 📊 STRATEGY DIVISION
| Agent | Role | Claude Project |
|-------|------|---------------|
| **QUANT** | Quantitative trader — signals & sizing | ✅ Created |
| **ORACLE** | Market intelligence — data fetcher & sentiment | ✅ Created |

### 🔨 BUILDER DIVISION
| Agent | Role | Claude Project |
|-------|------|---------------|
| **FORGE-X** | Backend engineer — core bot engine | ✅ Created |
| **PIXEL** | Pine Script & MQL EA developer | ✅ Created |
| **CANVAS** | Frontend & dashboard engineer | ✅ Created |
| **CONNECT** | Integration & pipeline engineer | ✅ Created |

### 🛡️ GUARDIAN DIVISION
| Agent | Role | Claude Project |
|-------|------|---------------|
| **SENTINEL** | Risk management — writes risk code | ✅ Created |
| **SCOUT** | Arbitrage scanner — writes scanner code | ✅ Created |
| **EVALUATOR** | Performance analyst — writes reporting code | ✅ Created |

### 🌐 EXTERNAL
| Agent | Role | Claude Project |
|-------|------|---------------|
| **BRIEFER** | Prompt maker for external AI assistance | ✅ Created |

---

## 📋 TEAM OPERATIONAL RULES

### BUILD MODE (when order received)
1. COMMAND receives order from founder
2. COMMAND analyzes → gives suggestions → asks approval
3. Founder approves → COMMAND delegates to agents
4. Agents build → test → deploy
5. COMMAND reports: "Program running ✅"
6. Team enters STANDBY MODE

### STANDBY MODE (after successful deploy)
- Full team idle — zero self-initiative
- Bot runs automatically 24/7
- Wait for: New Build / Maintenance / Feature / Bug Fix

### MAINTENANCE MODE (if issue reported)
- Founder reports bug/issue
- COMMAND identifies responsible agent
- Agent fixes → tests → redeploys
- Confirm resolved to founder

### DONE CRITERIA (every program must meet ALL)
```
✓ Code pushed to GitHub main branch
✓ README complete and accurate
✓ SENTINEL reviewed all risk logic
✓ Program running without error 24+ hours
✓ Founder confirms: "running well ✅"
✓ Team enters STANDBY
```

---

## 📁 GITHUB REPOSITORY STRUCTURE

```
trading-ai-team/
│
├── strategy/               ← QUANT + ORACLE
│   ├── signals.py
│   ├── sizing.py
│   ├── backtest.py
│   ├── config.yaml
│   └── oracle/
│       ├── news_fetcher.py
│       ├── sentiment.py
│       ├── drift_detector.py
│       └── data_schema.py
│
├── engine/                 ← FORGE-X
│   ├── core/
│   │   ├── order_manager.py
│   │   └── execution.py
│   ├── api/
│   ├── db/
│   └── utils/
│
├── indicators/             ← PIXEL
│   ├── pinescript/
│   ├── mql4/
│   └── mql5/
│
├── frontend/               ← CANVAS
│   └── src/
│       ├── components/
│       ├── pages/
│       ├── hooks/
│       └── services/
│
├── integrations/           ← CONNECT
│   ├── webhooks/
│   ├── brokers/
│   ├── alerts/
│   └── deploy/
│
├── risk/                   ← SENTINEL
│   ├── sentinel.py
│   ├── rules.yaml
│   ├── kill_switch.py
│   └── audit_log.py
│
├── strategy/scout/         ← SCOUT
│   ├── arb_scanner.py
│   ├── fee_calculator.py
│   └── opportunity_log.py
│
├── analytics/              ← EVALUATOR
│   ├── metrics.py
│   ├── evaluator.py
│   ├── report_generator.py
│   └── reports/
│
├── tools/briefer/          ← BRIEFER
│   ├── templates/
│   └── logs/
│
├── .env.example
├── requirements.txt
├── docker-compose.yml
├── PROJECT_STATE.md        ← THIS FILE
└── README.md
```

### Branch Naming Convention
```
feature/[agent-name]/[task-name]
Example: feature/forge/websocket-connection
         feature/quant/momentum-strategy
         feature/sentinel/drawdown-rules
```

---

## 🎯 PERFORMANCE TARGETS (all bots must meet)

```
Win Rate:          >70%
Avg Profit/Trade:  >$15
Max Drawdown:      <5%
Sharpe Ratio:      >2.5
Profit Factor:     >1.5
```

### Latency Budget
```
Data Ingestion:    <100ms
Signal Generation: <200ms
Order Execution:   <500ms  ← main bottleneck
End-to-End:        <1000ms
```

---

## 🛡️ RISK PARAMETERS (SENTINEL enforces in code)

```yaml
# /risk/rules.yaml
max_position_pct: 0.10          # 10% bankroll per position
max_concurrent_positions: 5
daily_loss_limit: -2000         # USD — pause if hit
max_drawdown_pct: 0.08          # 8% → block all trades
kelly_fraction: 0.25            # NEVER full Kelly
min_liquidity: 10000            # USD market depth
min_ev_threshold: 0.0           # EV must be positive
correlation_limit: 0.40         # max correlated exposure
var_confidence: 0.95
profit_factor_min: 1.5          # PF < 1.5 → review strategy
```

### CRITICAL RULE
```
⚠️ NEVER use full Kelly on 5-min markets!
→ Always use Fractional Kelly: f_final = 0.25 × f_kelly
```

---

## 📈 TRADING STRATEGIES (to be implemented)

### Level 1 — Beginner (build first)
- [ ] SMA Crossover — moving average signals
- [ ] Momentum — M = Pt − Pt-n trend riding

### Level 2 — Intermediate
- [ ] Mean Reversion — bet on return to average
- [ ] Bayesian Signal Processing — update beliefs with data
- [ ] Mispricing Score — Z-score entry filter

### Level 3 — Advanced
- [ ] ML/DL pattern recognition
- [ ] Bayesian Fusion — multi-signal combination
- [ ] Market Cost Function: C(q) = β·ln(Σ e^(qi/2))

### Arbitrage Strategies
- [ ] CEX vs PM spread arb (500ms lag exploit)
- [ ] CLOB spread capture
- [ ] Polymarket vs Kalshi cross-platform arb
- [ ] Both-sides volatility compression
- [ ] Resolution arbitrage

---

## 🏗️ BUILD ROADMAP (every program follows this)

```
Phase 1 — Foundation
  Step 1: Foundations & Setup
  Step 2: Data Infrastructure

Phase 2 — Strategy
  Step 3: Trading Strategies
  Step 4: Backtesting

Phase 3 — Intelligence
  Step 5: ML / Deep Learning (if needed)
  Step 6: Real-Time Trading Engine

Phase 4 — Production
  Step 7: Deployment
  Step 8: Final Pipeline — DONE → STANDBY
```

---

## 📊 CURRENT BUILD STATUS

### ✅ Completed
- Claude Projects setup (11 agents created)
- Team architecture defined
- GitHub repo structure defined
- Risk parameters defined
- Performance targets defined

### 🔄 In Progress
- Knowledge files creation (formulas.md, system_specs.md)
- GitHub repository creation

### ⏳ Not Started
- [ ] GitHub repo: trading-ai-team
- [ ] First bot build (Phase 1)
- [ ] Polymarket data pipeline
- [ ] First strategy implementation
- [ ] SENTINEL risk engine
- [ ] Dashboard

### 🎯 Next Priority
→ Create GitHub repo
→ Upload Knowledge files to all agents
→ Start Phase 1: Foundation with COMMAND + FORGE-X

---

## ⚠️ KNOWN DECISIONS & CONSTRAINTS

```
1. Smartphone only — no laptop/desktop
   → All tools must be mobile-accessible

2. Claude Pro usage limit
   → Rotate: Claude (planning) + Gemini (research)
   → Use Poe.com as overflow

3. NEVER full Kelly
   → Always fractional Kelly α = 0.25

4. SENTINEL must review before ANY live execution
   → No exceptions, even for small amounts

5. Every program must run 24+ hours error-free
   → Before founder confirms DONE

6. Surgical code changes preferred
   → No unnecessary rewrites
```

---

## 🔄 HOW TO UPDATE THIS FILE

After every working session, update:
1. `Last Updated` date at top
2. `Current Build Status` section
3. Any new decisions made
4. Any bugs discovered
5. Any completed items

Then re-upload to Knowledge section of ALL 11 agents.

---

## 📞 COMMUNICATION PROTOCOL

When agents communicate tasks:
```
FROM: [AGENT]
TO: [AGENT]
PRIORITY: High/Medium/Low
TYPE: Build/Fix/Review/Info

TASK: [specific atomic task]
INPUT: [what they need]
OUTPUT: [what to deliver]
BRANCH: feature/[agent]/[task]
DEPENDS ON: [other task or "none"]
```

---

*This document is the single source of truth for the AI Trading Team.
Always read this before starting any task.*
