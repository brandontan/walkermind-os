# Walker AI Trading Team — Project Roadmap

**Repo:** https://github.com/bayuewalker/walker-ai-team
**Team:** COMMANDER · FORGE-X · SENTINEL · BRIEFER

> **COMMANDER:** Update status fields (`✅` / `🚧` / `❌`) and Last Updated after every merge or phase milestone.
> This file covers all active projects. Add a new project section when a new project starts.

---

## Active Projects

| Project | Platform | Status | Current Phase |
|---|---|---|---|
| Crusader | Polymarket | Active (Paper Beta Complete + Phase 10 Execution) | Phase 10.3 — Monitor Integration + Observability Hardening |
| TradingView Indicators | TradingView (Pine Script v5) | ❌ Not Started | — |
| MT5 Expert Advisors | MT4/MT5 (MQL5) | ❌ Not Started | — |
| Kalshi Bot | Kalshi | ❌ Not Started | — |

---

# PROJECT: CRUSADER

**Description:** Non-custodial Polymarket trading platform — multi-user, closed beta first.  
**Tech Stack:** Python · FastAPI· PostgreSQL´ Redis· Polymarket CLOB API´ WebSocket´ Polygon· Telegram Bot· Fly.io  **Status:** Public-ready paper beta path (Phase 9.1/9.2/9.3) is complete on main; Phase 10.2 onboarding/public command-surface lane is merged truth on main, and Phase 10.3 monitor integration plus observability is completed on PR #718 pending COMMANDER review / merge (paper-only boundary preserved, no live-trading or production-capital claim)
**Last Updated:** 2026-04-22 21:20

# Board Overview

| Phase | Name | Status | Target |
|---|---|---|---|
| Phase 1 | Core Hardening | ✅ Done | Internal |
| Phase 2 | Platform Foundation | ✅ Done | Internal |
| Phase 3 | Execution-Safe MVP | ✅ Done | Closed Beta |
| Phase 4 | Execution Formalization & Boundaries | ✅ Done | Internal |
| Phase 5 | Real Execution & Capital System | ✅ Done | Internal |
| Phase 6 | Production Safety & Stabilization | ✅ Done | Public Preparation |
| Phase 7 | Orchestration & Automation Foundation | ✅ Done | Public Activation Orchestration |
| Phase 8 | Multi-User Foundation | ✅ Done | Multi-User Ownership + Auth/Session Scope |
| Phase 9 | Public-Ready Paper Beta Path | ✅ Done | Runtime Proof + Operational Readiness + Release Gate |
| Phase 10 | Public Runtime & Product Completion | 🚧 In Progress | Telegram runtime activation + public command validation + UX/persistence hardening |

---


## CrusaderBot — Current Delivery Focus (Phase 10)

**Roadmap Intent:** Keep ROADMAP.md as milestone-level planning truth and keep execution-level task tracking in `projects/polymarket/polyquantbot/work_checklist.md` .

### Current Focus Summary (paper-only boundary preserved)
- Phase 10.2 post-merge sync and public command-surface refinement is merged on main (PR #713) with paper-only/non-custodial posture preserved.
- Active Telegram public-safe command baseline is `/start`, `/help`, `/status`, `/paper`, `/about`, `/risk_info`, `/account`, and `/link`; runtime/operator `/risk` remains separate and is not part of the public-safe informational set.
- Phase 10.3 monitor integration hardening + observability baseline is completed on PR #718 and pending COMMANDER review / merge (admin/internal path guarding, startup/command/reply lifecycle logs, missing-env/disabled-mode logs, and monitor/admin visibility closure).
- Next execution lane remains Phase 10.3 merge + post-merge sync; post-launch cleanup + public-surface wording alignment follows after merged truth is recorded on main.

### Execution Tracking Source
- Detailed checklist, priority ordering, and right-now operational tasks live at: [projects/polymarket/polyquantbot/work_checklist.md](projects/polymarket/polyquantbot/work_checklist.md).
- ROADMAP.md remains summary-level and milestone-oriented.