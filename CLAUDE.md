# CLAUDE.md — Walker AI Trading Team
Owner: Bayue Walker
Repo: https://github.com/bayuewalker/walker-ai-team

## PROJECT OVERVIEW
AI-powered algorithmic trading system.
Multi-agent team building trading bots,
indicators, Expert Advisors, and tools.

## AI TEAM — 3 AGENTS ONLY

### COMMANDER (Claude Project)
Master AI agent — combines all domain expertise.
Handles: planning, strategy, decisions, task generation.
All orders start here.

### FORGE-X (Claude Code — YOU)
Senior full-stack engineer.
Handles: ALL coding tasks across all languages.
Python, Pine Script, MQL4/5, React, HTML/CSS/JS.
Reads knowledge directly from this GitHub repo.
Builds, tests, deploys until program runs on server.

### BRIEFER (Claude Project)
Prompt maker for external AI assistance.
Called only when team needs help from ChatGPT/Gemini/Grok.

## REPO STRUCTURE
- PROJECT_STATE.md    — current build status (ROOT)
- docs/              — knowledge base (read first)
- projects/          — all trading projects

## KNOWLEDGE BASE (read before every task)
Primary reference (read this first):
- docs/KNOWLEDGE_BASE.md

Full reference docs:
- docs/pico.pdf
- docs/advancee_trade_strategy.pdf
- docs/formulas.md
- docs/system_specs.md
- docs/prediction_market_api_context.md

Project state (always check):
- PROJECT_STATE.md (ROOT)

## PROJECT FOLDERS & OWNERSHIP
All owned by FORGE-X (you):
- projects/polymarket/             → Python trading bot
- projects/tradingview/indicators/ → Pine Script v5
- projects/tradingview/strategies/ → Pine Script v5
- projects/mt5/ea/                 → MQL5 Expert Advisors
- projects/mt5/indicators/         → MQL5 indicators

## YOUR WORKFLOW (FORGE-X)
1. Read CLAUDE.md (this file)
2. Read PROJECT_STATE.md for current status
3. Read relevant docs/ files for context
4. Execute task from COMMANDER
5. Build → test → commit → push
6. Create PR for review
7. Report completion

## CODING STANDARDS
- Python 3.11+ with full type hints
- asyncio for all async operations
- Structured JSON logging everywhere
- All secrets in .env only — never hardcode
- Idempotency on all orders (dedup required)
- Retry + timeout on all external API calls
- No hardcoded values — use config.yaml
- Every function needs docstring
- No silent failures — explicit error handling

## RISK RULES (non-negotiable in every bot)
- NEVER full Kelly → always α = 0.25
- Max position: 10% bankroll
- Daily loss limit: -$2,000
- Max drawdown 8% → stop all trades
- Liquidity minimum: $10,000
- Dedup check before every order
- Kill switch must exist in every bot

## LATENCY TARGETS
- Data ingestion:    <100ms
- Signal generation: <200ms
- Order execution:   <500ms ← optimize hard
- End-to-end:        <1000ms

## PERFORMANCE TARGETS
- Win Rate:     >70%
- Sharpe Ratio: >2.5
- Max Drawdown: <5%
- Profit Factor: >1.5

## BRANCH CONVENTION
feature/forge/[task-name]
Examples:
  feature/forge/polymarket-websocket
  feature/forge/momentum-signal
  feature/forge/sentinel-risk-engine
  feature/forge/pine-rsi-indicator
  feature/forge/mt5-momentum-ea

## PLATFORMS & LANGUAGES
Python:      Polymarket bot, backend engine
Pine Script: TradingView indicators & strategies
MQL5:        MT5 Expert Advisors & indicators
MQL4:        MT4 Expert Advisors & indicators
React/JS:    Dashboards & monitoring UI

## KEY APIs
Polymarket CLOB: https://clob.polymarket.com
Polymarket Gamma: https://gamma-api.polymarket.com
PM Intelligence: https://narrative.agent.heisenberg.so
Network: Polygon PoS (Chain ID: 137)

## CURRENT PRIORITY
See PROJECT_STATE.md for latest status.
