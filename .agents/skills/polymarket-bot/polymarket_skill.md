---
name: polymarket-bot-builder
description: "Specialized skill for building production-grade Polymarket trading bots. Supports multi-strategy, capital allocation, risk management, and execution systems."
---

# Polymarket Bot Builder Skill

## Project Context

**Repo:** github.com/bayuewalker/walker-ai-team  
**Bot location:** projects/polymarket/polyquantbot/  
**Owner:** Bayue Walker — sole decision maker  

---

## Architecture Overview (UPDATED — FINAL)

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
- All signals MUST include strategy_id
- SENTINEL is NOT part of runtime execution

---

## Execution Mode Control (CRITICAL)

MODE = "PAPER"  # or "LIVE"
ENABLE_LIVE_TRADING = False

---

## Conflict Resolution

def resolve_conflict(signals):
    sides = set(s.side for s in signals)
    if "YES" in sides and "NO" in sides:
        return None
    return signals[0]

---

## Capital Allocation

def calculate_score(ev, confidence, drawdown):
    return (ev * confidence) / (1 + drawdown)

def normalize_weights(scores):
    total = sum(scores)
    return [s / total for s in scores] if total > 0 else [0 for _ in scores]

Constraints:
- ≤ 5% per strategy
- ≤ 10% total exposure

---

## Risk Rules (Runtime)

RISK_CONFIG = {
    "max_position_pct": 0.10,
    "max_concurrent_positions": 5,
    "daily_loss_limit": -2000.0,
    "max_drawdown_pct": 0.08,
}

---

## File Structure (UPDATED — NO LEGACY)

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

## System Rules (CRITICAL)

- NO phase folders
- NO backward compatibility
- NO legacy structure
- Always use domain-based architecture
