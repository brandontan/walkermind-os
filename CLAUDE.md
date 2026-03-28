# CLAUDE.md — Walker AI Trading Team
Owner: Bayue Walker
Repo: https://github.com/bayuewalker/walker-ai-team

## PROJECT OVERVIEW
AI-powered algorithmic trading system.
Multi-agent team building trading bots,
indicators, and tools.

## REPO STRUCTURE
- /docs/         — knowledge base (read first)
- /projects/     — all trading projects
  Each project isolated in own folder

## KNOWLEDGE BASE (always read these first)
- PROJECT_STATE.md        — current project state (ROOT)
- docs/formulas.md        — core trading formulas
- docs/system_specs.md    — technical specifications

## PROJECT FOLDERS & OWNERSHIP
/projects/polymarket/              → FORGE-X
/projects/tradingview/indicators/  → PIXEL
/projects/tradingview/strategies/  → PIXEL
/projects/mt5/ea/                  → PIXEL
/projects/mt5/indicators/          → PIXEL
/docs/                             → COMMAND

## CODING STANDARDS
- Python 3.11+ with full type hints
- asyncio for all async operations
- Structured JSON logging everywhere
- All secrets in .env only — never hardcode
- Idempotency on all orders (dedup required)
- Retry + timeout on all external API calls
- No hardcoded values — use config.yaml
- Every function needs docstring

## RISK RULES (non-negotiable)
- NEVER full Kelly → always α = 0.25
- SENTINEL must approve before any live execution
- Max position: 10% bankroll
- Daily loss limit: -$2,000
- MDD > 8% → stop all trades immediately

## BRANCH CONVENTION
feature/[agent]/[task-name]
Example: feature/forge/websocket-connection
         feature/pixel/rsi-indicator
         feature/pixel/momentum-ea

## CURRENT PRIORITY
Phase 1: Build polymarket foundation
See PROJECT_STATE.md for latest status
