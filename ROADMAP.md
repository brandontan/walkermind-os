# Walker AI Trading Team — Project Roadmap

**Repo:** https://github.com/bayuewalker/walker-ai-team
**Team:** COMMANDER · FORGE-X · SENTINEL · BRIEFER

> **COMMANDER:** Update status fields (`✅` / `🚧` / `❌`) and Last Updated after every merge or phase milestone.
> This file covers all active projects. Add a new project section when a new project starts.

---

## Active Projects

| Project | Platform | Status | Current Phase |
|---|---|---|---|
| Crusader | Polymarket | 🚧 Active | Phase 6 — Production Safety & Stabilization |
| TradingView Indicators | TradingView (Pine Script v5) | ❌ Not Started | — |
| MT5 Expert Advisors | MT4/MT5 (MQL5) | ❌ Not Started | — |
| Kalshi Bot | Kalshi | ❌ Not Started | — |

---

# PROJECT: CRUSADER

**Description:** Non-custodial Polymarket trading platform — multi-user, closed beta first.
**Tech Stack:** Python · FastAPI · PostgreSQL · Redis · Polymarket CLOB API · WebSocket · Polygon · Telegram Bot · Fly.io
**Status:** 🚧 In Progress
**Last Updated:** 2026-04-15 11:02

## Board Overview

| Phase | Name | Status | Target |
|---|---|---|---|
| Phase 1 | Core Hardening | ✅ Done | Internal |
| Phase 2 | Platform Foundation | ✅ Done | Internal |
| Phase 3 | Execution-Safe MVP | ✅ Done | Closed Beta |
| Phase 4 | Execution Formalization & Boundaries | ✅ Done | Internal |
| Phase 5 | Real Execution & Capital System | ✅ Done | Internal |
| Phase 6 | Production Safety & Stabilization | 🚧 In Progress | Public Preparation |

---

## 🚧 Phase 6 — Production Safety & Stabilization

**Goal:** Ensure production-grade safety, stability, and operational truth.
**Status:** 🚧 In Progress
**Last Updated:** 2026-04-15 11:02

| Sub-Phase | Name | Status | Notes |
|---|---|---|---|
| 6.1 | Execution Ledger (In-Memory) | ✅ Done | Deterministic append-only records and read-only reconciliation delivered. |
| 6.2 | Persistent Ledger & Audit Trail | ✅ Done | Append-only local-file persistence and deterministic reload delivered. |
| 6.3 | Kill Switch & Execution Halt Foundation | ✅ Done | Merged via PR #479 and preserved as approved carry-forward truth. |
| 6.4.1 | Monitoring & Circuit Breaker FOUNDATION Spec Contract | 🚧 In Progress | Approved at spec level only; runtime-wide delivery is not claimed. |
| 6.4.2 | Runtime Monitoring Narrow Integration | ✅ Done | Merged truth preserved for ExecutionTransport.submit_with_trace narrow integration after SENTINEL APPROVED (95/100). |
| 6.4.3 | Authorizer-Path Monitoring Narrow Integration | ✅ Done | Merged via PR #491. SENTINEL APPROVED (99/100). Narrow scope: LiveExecutionAuthorizer.authorize_with_trace + ExecutionTransport.submit_with_trace preserved. No platform-wide rollout. |
| 6.4.4 | Gateway-Path Monitoring Narrow Integration Expansion | ✅ Done | Runtime/code path merged via PR #493. SENTINEL APPROVED validation path recorded in PR #495 (97/100). Accepted narrow three-path execution monitoring baseline: ExecutionTransport.submit_with_trace + LiveExecutionAuthorizer.authorize_with_trace + ExecutionGateway.simulate_execution_with_trace. No platform-wide rollout. |
| 6.4.5 | Exchange-Path Monitoring Narrow Integration Expansion | ✅ Done | Merged truth confirmed after PR #497 and PR #498 at declared narrow scope. Accepted four execution-related runtime paths: ExecutionTransport.submit_with_trace, LiveExecutionAuthorizer.authorize_with_trace, ExecutionGateway.simulate_execution_with_trace, ExchangeIntegration.execute_with_trace. Explicit exclusions preserved: no platform-wide rollout, scheduler generalization, wallet lifecycle expansion, portfolio orchestration, or settlement automation. |
| 6.4.6 | Signing-Boundary Monitoring Narrow Integration Expansion | ✅ Done | Merged-main truth confirmed after PR #501 and PR #502 at declared narrow scope. Accepted five execution-related runtime paths: ExecutionTransport.submit_with_trace, LiveExecutionAuthorizer.authorize_with_trace, ExecutionGateway.simulate_execution_with_trace, ExchangeIntegration.execute_with_trace, SecureSigningEngine.sign_with_trace. Explicit exclusions preserved: no platform-wide monitoring rollout, scheduler generalization, wallet lifecycle expansion, portfolio orchestration, or settlement automation. |
| 6.4.7 | Capital-Boundary Monitoring Narrow Integration Expansion | ✅ Done | Merged-main truth confirmed after PR #504 and PR #505 at declared narrow scope. Accepted six execution-related runtime paths: ExecutionTransport.submit_with_trace, LiveExecutionAuthorizer.authorize_with_trace, ExecutionGateway.simulate_execution_with_trace, ExchangeIntegration.execute_with_trace, SecureSigningEngine.sign_with_trace, WalletCapitalController.authorize_capital_with_trace. Explicit exclusions preserved: no platform-wide monitoring rollout, scheduler generalization, wallet lifecycle expansion, portfolio orchestration, or settlement automation. |
| 6.4.8 | Settlement-Boundary Monitoring Narrow Integration Expansion | ✅ Done | Merged-main truth accepted for narrow settlement boundary at FundSettlementEngine.settle_with_trace with deterministic ALLOW/BLOCK/HALT monitoring decisions. Seven-path baseline preserved through settlement boundary; no platform-wide monitoring rollout claimed. |
| 6.4.9 | Orchestration-Entry Monitoring Narrow Integration Expansion | 🚧 In Progress | FORGE-X scope active for narrow orchestration-entry boundary at ExecutionActivationGate.evaluate_with_trace with deterministic ALLOW/BLOCK/HALT monitoring decisions. Existing seven accepted monitored paths are preserved; no platform-wide monitoring rollout claimed. |

---

## ⚪ PROJECT: TRADINGVIEW INDICATORS

**Description:** Custom indicators for TradingView using Pine Script v5.
**Tech Stack:** Pine Script v5
**Status:** ❌ Not Started
**Last Updated:** —

### Board Overview

| Phase | Name | Status | Target |
|---|---|---|---|
| Phase 1 | Indicator Development | ❌ Not Started | — |
| Phase 2 | Backtesting & Validation | ❌ Not Started | — |

---

## ⚪ PROJECT: MT5 EXPERT ADVISORS

**Description:** MetaTrader 4/5 Expert Advisors for automated trading.
**Tech Stack:** MQL5 · MQL4
**Status:** ❌ Not Started
**Last Updated:** —

### Board Overview

| Phase | Name | Status | Target |
|---|---|---|---|
| Phase 1 | EA Development | ❌ Not Started | — |
| Phase 2 | Backtesting & Optimization | ❌ Not Started | — |
| Phase 3 | Live Deployment | ❌ Not Started | — |

---

## ⚪ PROJECT: KALSHI BOT

**Description:** Algorithmic trading bot for Kalshi prediction market.
**Tech Stack:** Python · Kalshi API
**Status:** ❌ Not Started
**Last Updated:** —

### Board Overview

| Phase | Name | Status | Target |
|---|---|---|---|
| Phase 1 | Core Strategy | ❌ Not Started | — |
| Phase 2 | Execution & Risk | ❌ Not Started | — |
| Phase 3 | Production Deploy | ❌ Not Started | — |

---

## COMMANDER — Roadmap Maintenance

### Status Legend
- ✅ = Done (merged + validated)
- 🚧 = In Progress
- ❌ = Not Started

### Update Triggers

| Event | Action |
|---|---|
| FORGE-X PR merged | Task `❌` / `🚧` → `✅`, add PR # and date in notes |
| SENTINEL APPROVED | Confirm status truthfully and add score in notes when relevant |
| Phase complete | Update phase header and Active Projects table |
| New task scoped | Add row with `❌` or `🚧` as appropriate |
| New project activated | Fill phases/tasks and update Active Projects table |

### Commit Format

```text
docs: update ROADMAP.md — [project] [task or phase name]
