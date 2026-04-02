name: polymarket-bot-builder-v2

description: >
Production-grade Polymarket trading system skill aligned with Walker AI architecture.
Supports multi-strategy, capital allocation, risk enforcement, and async execution.

---

🔥 POLYQUANTBOT BUILDER (V2 — FINAL)

🧠 SYSTEM CONTEXT

Repo: github.com/bayuewalker/walker-ai-team
Bot: projects/polymarket/polyquantbot/
Owner: Bayue Walker

---

🏗 ARCHITECTURE (LOCKED)

DATA (WebSocket + API)
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
EXECUTION (paper/live)
   ↓
MONITORING (metrics + alerts)

---

🔒 HARD RULES

- NO phase folders
- NO legacy structure
- NO backward compatibility
- Domain-based only

---

⚙️ EXECUTION CONTROL (CRITICAL)

MODE = PAPER | LIVE
ENABLE_LIVE_TRADING = true | false

---

Behavior:

- PAPER → simulator only
- LIVE + false → dry-run
- LIVE + true → real execution

---

🧠 MULTI-STRATEGY SYSTEM

Each strategy:

- independent signal generation
- tagged with strategy_id

---

Conflict Rule:

YES + NO → SKIP (no trade)

---

💰 CAPITAL ALLOCATION (CORE)

def calculate_score(ev, confidence, drawdown):
    return (ev * confidence) / (1 + drawdown)

def normalize_weights(scores):
    total = sum(scores)
    return [s / total for s in scores]

---

Constraints:

- ≤ 5% per strategy
- ≤ 10% total exposure

---

🛡 RISK SYSTEM (RUNTIME)

def check_risk(order, portfolio):
    if portfolio.drawdown > 0.08:
        return False
    if portfolio.daily_loss < -2000:
        return False
    return True

---

❗ SENTINEL (IMPORTANT)

- NOT part of runtime
- ONLY validation agent

---

🛠 ENGINEERING STANDARDS

- asyncio only
- retry + timeout
- idempotent orders
- structured logging
- no silent failure

---

🔁 DEDUP REQUIRED

Every order must be idempotent.

---

📊 TELEGRAM

- alerts
- allocation report
- system status

---

⚡ LATENCY TARGET

- ingestion <100ms
- signal <200ms
- execution <500ms

---

🚨 COMMON ERRORS

- mixing signal & execution ❌
- no execution guard ❌
- no allocation ❌
- ignoring conflict ❌

---

🎯 PRINCIPLE

This is NOT a single-strategy bot.

This is a:

🔥 MULTI-STRATEGY CAPITAL-ALLOCATED TRADING SYSTEM
