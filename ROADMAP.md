# Walker AI Trading Team — Project Roadmap
**Repo:** https://github.com/bayuewalker/walker-ai-team
**Team:** COMMANDER · FORGE-X · SENTINEL · BRIEFER

> **COMMANDER:** Update status fields (`✅` / `🚧` / `❌`) and Last Updated after every merge or phase milestone.
> This file covers ALL active projects. Add new project section when a new project starts.

---

## 🗂️ Active Projects

| Project | Platform | Status | Current Phase |
|---|---|---|---|
| Crusader | Polymarket | 🚧 Active | Phase 2 — Platform Foundation |
| TradingView Indicators | TradingView (Pine Script v5) | ❌ Not Started | — |
| MT5 Expert Advisors | MT4/MT5 (MQL5) | ❌ Not Started | — |
| Kalshi Bot | Kalshi | ❌ Not Started | — |

---

---

# 🟢 PROJECT: CRUSADER
**Description:** Non-Custodial Polymarket Trading Platform — Multi-User, Closed Beta First
**Tech Stack:** Python · FastAPI · PostgreSQL · Redis · Polymarket CLOB API · WebSocket · Polygon · Telegram Bot · Fly.io
**Last Updated:** 2026-04-11

## Board Overview

| Phase | Name | Status | Target |
|---|---|---|---|
| Phase 1 | Core Hardening | ✅ Done | Internal |
| Phase 2 | Platform Foundation | 🚧 In Progress | Internal |
| Phase 3 | Execution-Safe MVP | ❌ Not Started | Closed Beta |
| Phase 4 | Multi-User Public Architecture | ❌ Not Started | Closed Beta → Public |
| Phase 5 | Funding UX & Convenience | ❌ Not Started | Public |
| Phase 6 | Public Launch & Stabilization | ❌ Not Started | Public |

---

## ✅ Phase 1 — Core Hardening
**Goal:** Build and harden the protected trading core — strategy, risk, execution, observability, and Telegram UI.
**Status:** ✅ DONE
**Last Updated:** 2026-04-11

### Trading Strategies
| # | Task | Status | Notes |
|---|---|---|---|
| S1 | Breaking-news / narrative momentum strategy | ✅ | Merged |
| S2 | Cross-exchange arbitrage (Polymarket ↔ Kalshi) | ✅ | Merged |
| S3 | Smart-money / copy-trading strategy | ✅ | Merged |
| S3.1 | Smart-money wallet quality upgrade (H-Score + Wallet 360) | ✅ | Merged |
| S4 | Strategy aggregation & prioritization | ✅ | Merged |
| S5 | Settlement-gap scanner | ✅ | Merged |

### Execution & Risk
| # | Task | Status | Notes |
|---|---|---|---|
| P7 | Capital allocation & position sizing | ✅ | Merged |
| P8 | Portfolio exposure balancing & correlation guard | ✅ | Merged |
| P9 | Performance feedback loop | ✅ | Merged |
| P10 | Execution quality & fill optimization | ✅ | Merged |
| P11 | Market regime detection | ✅ | Merged |
| P12 | Execution timing & entry optimization | ✅ | Merged |
| P13 | Exit timing & trade management | ✅ | Merged |
| P14 | Post-trade analytics & attribution | ✅ | Merged |
| P14.1 | System optimization from analytics | ✅ | Merged |
| P14.2 | External alpha ingestion (Falcon API) | ✅ | Merged |
| P14.3 | Falcon alpha strategy layer | ✅ | Merged |
| P15 | Strategy selection & auto-weighting | ✅ | Merged |
| P16 | Execution-boundary validation-proof enforcement | ✅ | Merged |
| P16 | Execution-boundary position-sizing enforcement | ✅ | Merged |
| P17 | Execution proof lifecycle (TTL, replay safety, DB registry) | ✅ | PR #394, SENTINEL 96/100, 2026-04-11 |

### Trade System Hardening
| # | Task | Status | Notes |
|---|---|---|---|
| P2 | Risk-before-execution, dedup, restart/restore correctness | ✅ | Merged — SENTINEL APPROVED |
| P3 | Capital guardrails & structured blocking outcomes | ✅ | Merged — SENTINEL 97/100 |
| P4 | Runtime observability & trace propagation | ✅ | Merged |

### Telegram UI
| # | Task | Status | Notes |
|---|---|---|---|
| TG-1 | Market title canonicalization | ✅ | Merged |
| TG-2 | Open positions visibility | ✅ | Merged |
| TG-3 | Trade history | ✅ | Merged |
| TG-4 | Menu structure & market scope control | ✅ | Merged — SENTINEL 96/100 |
| TG-5 | Scope state persistence & category inference | ✅ | Merged |
| TG-6 | Premium navigation / UX consolidation | ✅ | Merged |
| TG-7 | Trade lifecycle alerts & scan presence | ✅ | Merged |
| TG-8 | UI text leakage audit | ✅ | Merged |

---

## 🚧 Phase 2 — Platform Foundation
**Goal:** Extract legacy core into protected kernel, build platform shell, establish multi-user DB schema, and introduce execution isolation boundary.
**Status:** 🚧 In Progress
**Last Updated:** 2026-04-11

> ⚠️ NOTE: PR #396 (ExecutionIsolationGateway) is Phase 2 work — branch/report naming used legacy "Phase 3" labels, but milestone ownership remains Phase 2.
> ✅ Merge + validation status: PR #396 merged on 2026-04-11 after SENTINEL rerun approval (`projects/polymarket/polyquantbot/reports/sentinel/24_56_pr396_execution_isolation_rerun.md`).

### Core Extraction & Isolation
| # | Task | Status | Notes |
|---|---|---|---|
| 2.1 | Freeze legacy core behavior (no logic drift) | 🚧 | PR #394 merged — stable, not formally tagged |
| 2.2 | Extract core module boundaries | 🚧 | Structure exists, formal boundary not declared |
| 2.3 | Add ExecutionIsolationGateway | ✅ | PR #396 merged (2026-04-11) — SENTINEL rerun approved before merge |
| 2.4 | Preserve resolver/bridge purity (read-only) | ✅ | Delivered in PR #396 chain; compatibility fixes included in follow-up `24_55` pass before merge |
| 2.5 | Regression tests around execution path | ✅ | Covered in PR #396 chain and SENTINEL rerun (`24_56`) with passing focused checks |

### Platform Shell
| # | Task | Status | Notes |
|---|---|---|---|
| 2.6 | Create platform folder structure (platform/gateway, accounts, wallet_auth) | ❌ | |
| 2.7 | Build public API/app gateway skeleton | ❌ | |
| 2.8 | Add legacy-core facade adapter | ❌ | |
| 2.9 | Add dual-mode routing (legacy + platform path) | ❌ | |
| 2.10 | Staging deploy on Fly.io | ❌ | Migration from Railway pending |

### Multi-User DB Schema
| # | Task | Status | Notes |
|---|---|---|---|
| 2.11 | Design multi-user DB schema (users, accounts, wallets, risk, proofs, audit) | ❌ | |
| 2.12 | Add audit/event log schema | ❌ | |
| 2.13 | Add wallet context abstraction | ❌ | |

---

## ❌ Phase 3 — Execution-Safe MVP
**Goal:** Single-user MVP on Polymarket wallet/auth with live/paper modes via Telegram.
**Status:** ❌ Not Started
**Target:** Closed Beta Entry Point

| # | Task | Status | Notes |
|---|---|---|---|
| 3.1 | Implement wallet/auth service | ❌ | |
| 3.2 | Add wallet type + signature type mapping | ❌ | |
| 3.3 | Add per-user auth state tracking | ❌ | |
| 3.4 | Extend execution proof with user context | ❌ | |
| 3.5 | Add idempotent execution submit/cancel/query flow | ❌ | |
| 3.6 | Implement live/paper mode at user context level | ❌ | Paper mode default for beta |
| 3.7 | Add Telegram public wallet overview (/balance, /positions) | ❌ | |
| 3.8 | Build reconciliation service baseline | ❌ | |
| 3.9 | Add user WebSocket manager | ❌ | |
| 3.10 | Add market WebSocket fanout manager | ❌ | |
| 3.11 | Focused runtime tests (auth → trade → reconcile) | ❌ | |

---

## ❌ Phase 4 — Multi-User Public Architecture
**Goal:** Scale to 5–10 closed beta users with isolated execution context.
**Status:** ❌ Not Started
**Target:** Closed Beta Full

| # | Task | Status | Notes |
|---|---|---|---|
| 4.1 | Per-user account binding | ❌ | |
| 4.2 | Strategy subscription model | ❌ | |
| 4.3 | Per-user risk profiles (conservative/balanced/aggressive) | ❌ | Default: balanced |
| 4.4 | Risk & permission service | ❌ | |
| 4.5 | Execution queue with priorities (Redis-based) | ❌ | |
| 4.6 | Retry + dead-letter handling | ❌ | |
| 4.7 | Upgrade Telegram menu for platform model | ❌ | |
| 4.8 | Notifications service | ❌ | |
| 4.9 | Admin dashboard | ❌ | |
| 4.10 | Audit replay / incident tools | ❌ | |
| 4.11 | Integration/load testing (5–10 concurrent users) | ❌ | |

---

## ❌ Phase 5 — Funding UX & Convenience
**Goal:** Add deposit/withdraw convenience without touching trading core.
**Status:** ❌ Not Started
**Target:** Post-Beta

| # | Task | Status | Notes |
|---|---|---|---|
| 5.1 | Funding transaction model | ❌ | |
| 5.2 | Deposit UX flow | ❌ | |
| 5.3 | Withdraw UX flow | ❌ | |
| 5.4 | Transaction tracking | ❌ | |
| 5.5 | Bridge quote provider integration | ❌ | |
| 5.6 | Stuck-funding admin tools | ❌ | |
| 5.7 | Extend reconciliation to funding state | ❌ | |
| 5.8 | End-to-end funding tests | ❌ | |

---

## ❌ Phase 6 — Public Launch & Stabilization
**Goal:** Launch safely, monitor aggressively, harden operations.
**Status:** ❌ Not Started
**Target:** Public Launch

| # | Task | Status | Notes |
|---|---|---|---|
| 6.1 | Production deploy on Fly.io | ❌ | |
| 6.2 | Alerting and runtime dashboards | ❌ | |
| 6.3 | Controlled onboarding rollout | ❌ | |
| 6.4 | Monitor execution success rate | ❌ | Target: 99%+ |
| 6.5 | UX iteration pass | ❌ | |
| 6.6 | Ops incident runbook | ❌ | |
| 6.7 | Documentation publish (user/admin/API) | ❌ | |

---

## Success Metrics — Crusader

| Metric | Closed Beta | Public Beta | Launch |
|---|---|---|---|
| Execution success rate | 95% | 98% | 99%+ |
| Reconciliation convergence | <60s | <20s | <10s |
| Telegram portfolio freshness | <30s | <5s | <2s |
| Concurrent users | 5–10 | 100+ | 500+ |
| Duplicate execution rate | <1% | <0.2% | <0.1% |
| Tenant isolation incidents | 0 | 0 | 0 |

---

---

# ⚪ PROJECT: TRADINGVIEW INDICATORS
**Description:** Pine Script v5 indicators and strategies for TradingView
**Tech Stack:** Pine Script v5
**Status:** ❌ Not Started
**Last Updated:** —

## Board Overview

| Phase | Name | Status | Target |
|---|---|---|---|
| Phase 1 | Indicator Development | ❌ Not Started | — |
| Phase 2 | Strategy Development | ❌ Not Started | — |
| Phase 3 | Publishing & Maintenance | ❌ Not Started | — |

> COMMANDER: Fill in phases and tasks when this project becomes active.

---

---

# ⚪ PROJECT: MT5 EXPERT ADVISORS
**Description:** MQL5 Expert Advisors and indicators for MT4/MT5
**Tech Stack:** MQL5 · MQL4
**Status:** ❌ Not Started
**Last Updated:** —

## Board Overview

| Phase | Name | Status | Target |
|---|---|---|---|
| Phase 1 | EA Development | ❌ Not Started | — |
| Phase 2 | Backtesting & Optimization | ❌ Not Started | — |
| Phase 3 | Live Deployment | ❌ Not Started | — |

> COMMANDER: Fill in phases and tasks when this project becomes active.

---

---

# ⚪ PROJECT: KALSHI BOT
**Description:** Algorithmic trading bot for Kalshi prediction market
**Tech Stack:** Python · Kalshi API
**Status:** ❌ Not Started
**Last Updated:** —

## Board Overview

| Phase | Name | Status | Target |
|---|---|---|---|
| Phase 1 | Core Strategy | ❌ Not Started | — |
| Phase 2 | Execution & Risk | ❌ Not Started | — |
| Phase 3 | Production Deploy | ❌ Not Started | — |

> COMMANDER: Fill in phases and tasks when this project becomes active.

---

---

## 🔄 COMMANDER — Roadmap Maintenance

### Status Legend
- ✅ = Done (merged + validated)
- 🚧 = In Progress
- ❌ = Not Started

### Update Triggers
| Event | Action |
|---|---|
| FORGE-X PR merged | Task ❌/🚧 → ✅, add PR # + date in Notes |
| SENTINEL APPROVED | Confirm ✅, add score in Notes |
| Phase complete | Update Phase header + Active Projects table at top |
| New task scoped | Add row with ❌ |
| New project activated | Fill phases/tasks, update Active Projects table |

### Commit Format
```
docs: update ROADMAP.md — [project] [task or phase name]
```

### Adding a New Project
1. Copy a ⚪ PROJECT template block
2. Change color to 🟢 and status to 🚧 Active
3. Fill in Description, Tech Stack, Board Overview, and Phase tasks
4. Update Active Projects table at top of file
5. Commit: `docs: update ROADMAP.md — add [project name]`

### Drift Control
If ROADMAP.md contradicts PROJECT_STATE.md:
→ STOP → report to Mr. Walker → PROJECT_STATE.md = source of truth → sync ROADMAP.md → wait approval

---

*Walker AI Trading Team — Build. Deploy. Profit. Repeat.*
*Bayue Walker © 2026*
