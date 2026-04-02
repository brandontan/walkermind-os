name: polymarket-bot-builder
description: >Specialized skill for building production-grade Polymarket trading bots. Supports multi-strategy, capital allocation, risk management, and execution systems.

Polymarket Bot Builder Skill

Project Context

Repo: github.com/bayuewalker/walker-ai-team
Bot location: projects/polymarket/polyquantbot/
Owner: Bayue Walker — sole decision maker

---

Architecture Overview (UPDATED — FINAL)

MARKET DATA (Gamma API + CLOB WebSocket)
        ↓
STRATEGY (multi-strategy engine)
        ↓
CONFLICT RESOLUTION (YES vs NO → SKIP)
        ↓
CAPITAL ALLOCATION (dynamic weighting)
        ↓
INTELLIGENCE (Bayesian + Drift)
        ↓
RISK (hard limits)
        ↓
EXECUTION (CLOB paper/live)
        ↓
STATE (PostgreSQL + Redis)
        ↓
NOTIFICATIONS (Telegram)
        ↓
ANALYTICS (metrics + reports)

NOTE:

- This is a multi-strategy system
- All signals MUST include "strategy_id"
- SENTINEL is NOT part of runtime execution

---

Execution Mode Control (CRITICAL)

MODE = "PAPER"  # or "LIVE"
ENABLE_LIVE_TRADING = False

def is_live_execution_enabled() -> bool:
    return MODE == "LIVE" and ENABLE_LIVE_TRADING

---

Core APIs

Polymarket Gamma API

BASE_URL = "https://gamma-api.polymarket.com"

Polymarket CLOB API

BASE_URL = "https://clob.polymarket.com"

Intelligence API

BASE_URL = "https://narrative.agent.heisenberg.so"

---

Core Formulas

def calculate_ev(p_model: float, decimal_odds: float) -> float:
    b = decimal_odds - 1
    return p_model * b - (1 - p_model)

def calculate_edge(p_model: float, p_market: float) -> float:
    return p_model - p_market

def calculate_kelly(p: float, b: float, alpha: float = 0.25) -> float:
    q = 1 - p
    return alpha * ((p * b - q) / b)

---

Conflict Resolution

def resolve_conflict(signals: list):
    sides = set(s.side for s in signals)
    if "YES" in sides and "NO" in sides:
        return None  # SKIP
    return signals[0]

---

Capital Allocation (CORE)

def calculate_score(ev: float, confidence: float, drawdown: float) -> float:
    return (ev * confidence) / (1 + drawdown)

def normalize_weights(scores: list[float]) -> list[float]:
    total = sum(scores)
    return [s / total for s in scores] if total > 0 else [0 for _ in scores]

Constraints:

- ≤ 5% per strategy
- ≤ 10% total exposure

---

Risk Rules (Runtime)

RISK_CONFIG = {
    "max_position_pct": 0.10,
    "max_concurrent_positions": 5,
    "daily_loss_limit": -2000.0,
    "max_drawdown_pct": 0.08,
}

def check_risk(order, portfolio):
    if portfolio.drawdown > RISK_CONFIG["max_drawdown_pct"]:
        return False
    if portfolio.daily_pnl < RISK_CONFIG["daily_loss_limit"]:
        return False
    return True

NOTE:

- This is RUNTIME risk system
- SENTINEL is only for validation (pre-live)

---

Engineering Patterns

- asyncio only
- retry + timeout required
- idempotent orders
- structured logging
- no silent failure

---

Telegram Integration

- trade alerts
- allocation report
- system status

---

Latency Targets

- ingestion <100ms
- signal <200ms
- execution <500ms

---

File Structure (UPDATED — NO LEGACY)

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

---

System Rules (CRITICAL)

- NO phase folders
- NO backward compatibility
- NO legacy structure
- Always use domain-based architecture

---

Push Rules

- Max 5 files per batch
- Branch: feature/forge/[task-name]
- Commit incrementally
