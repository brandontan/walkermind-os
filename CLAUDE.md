## CLAUDE.md — Walker AI Trading Team (FINAL)

Owner: Bayue Walker
Repo: github.com/bayuewalker/walker-ai-team

---

## 🧠 PROJECT OVERVIEW

AI-powered trading system for prediction markets.

System is designed as a multi-strategy portfolio engine with:

- real-time execution
- dynamic capital allocation
- strict risk enforcement
- production-grade architecture

---

## 👥 AI TEAM — 4 AGENTS

COMMANDER (Claude Project)

- Planning, validation, decisions
- Generates all tasks
- Final authority

---

## FORGE-X (Claude Code)

- Implementation (ALL code)
- Builds production-ready systems
- Must follow strict engineering rules

---

## SENTINEL

- Testing & validation ONLY
- Pre-live and post-build validation
- NEVER part of runtime execution

---

## BRIEFER

- Prompt generation
- UI / report design
- External AI coordination

---

## 🏗 SYSTEM ARCHITECTURE (LOCKED)

Pipeline:

DATA → STRATEGY → CONFLICT → ALLOCATION → INTELLIGENCE → RISK → EXECUTION → MONITORING

---

Domain Structure (MANDATORY):

- core/
- data/
- strategy/
- intelligence/
- risk/
- execution/
- monitoring/
- api/
- infra/
- backtest/
- reports/

---

## ❌ FORBIDDEN:

- phase1/, phase2/, ...
- backward compatibility layers
- shim imports

---

## 🔒 CORE SYSTEM RULES

1. NO LEGACY STRUCTURE

- ZERO phase folders allowed
- ZERO old imports allowed
- DELETE, do NOT migrate with compatibility

---

2. REPORT STRUCTURE (MANDATORY)

All reports MUST go to:

projects/polymarket/polyquantbot/reports/

Per agent:

- reports/forge/
- reports/sentinel/
- reports/briefer/

---

Naming:

[number]_[name].md

Examples:

- 11_1_cleanup.md
- 12_multi_strategy.md
- 13_capital_allocation.md

---

3. PROJECT STATE (MANDATORY)

After EVERY FORGE-X task:

- update PROJECT_STATE.md
- must reflect real system state
- no outdated info allowed

---

4. FAIL-FAST RULE

If:

- instruction unclear
- rule conflict

→ STOP and ask
→ DO NOT improvise

---

## ⚙️ EXECUTION CONTROL SYSTEM

MODE SYSTEM (CRITICAL)

MODE = PAPER | LIVE
ENABLE_LIVE_TRADING = true | false

---

Behavior:

MODE| ENABLE_LIVE_TRADING| Result
PAPER| false| simulator
LIVE| false| dry-run
LIVE| true| REAL execution

---

## ❗ RULE:

Real trading ONLY allowed if BOTH true.

---

## 🧠 TRADING ENGINE

Multi-Strategy System

- Multiple strategies run in parallel
- StrategyRouter handles evaluation
- ConflictResolver enforces:

YES vs NO → SKIP

---

Capital Allocation Engine

Score:

score = (EV × confidence) / (1 + drawdown)

Weight:

weight_i = score_i / sum(score_all)

Position:

position_size = weight × max_position_limit

---

Risk System (HIGHEST PRIORITY)

- max position ≤ 10%
- max per strategy ≤ 5%
- max 5 concurrent trades
- drawdown > 8% → BLOCK ALL
- daily loss limit → PAUSE

---

## 🧪 SENTINEL ROLE (STRICT)

- Testing ONLY
- Pre-live validation
- Stress & failure testing

❌ NOT:

- runtime risk engine
- execution decision layer

---

## 🛠 ENGINEERING STANDARDS

- Python 3.11+
- asyncio ONLY
- full typing
- structured JSON logging
- idempotent systems
- retry + timeout on ALL external calls
- no silent failure

---

## 📊 DATA & INFRA

- PostgreSQL (state)
- Redis (real-time cache)
- InfluxDB (metrics)

---

## 🚀 DEPLOYMENT RULE

NEVER:

- go LIVE without Sentinel validation
- use full capital immediately

---

ALWAYS:

- start with small capital (≤2%)
- observe 24–48h
- scale gradually

---

## 🎯 MISSION

Build → Validate → Deploy → Confirm → STANDBY

System runs 24/7 after deploy.
Team waits for next instruction.

---

## 🔥 FINAL PRINCIPLE

Correctness > completeness
Safety > profit
Clarity > speed
No ambiguity EVER
