# Crusader — Platform Roadmap
**Project:** Crusader (formerly PolyQuantBot / Krusader)
**Target:** Non-Custodial Polymarket Trading Platform — Multi-User, Closed Beta First
**Tech Stack:** Python · FastAPI · PostgreSQL · Redis · Polymarket CLOB API · WebSocket · Polygon · Telegram Bot · Fly.io

> **COMMANDER:** Update status fields (`✅` / `🚧` / `❌`) and Last Updated date after every completed task or phase milestone.

---

## 🗂️ Board Overview

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
| P17 | Execution proof lifecycle (TTL, replay safety, DB registry) | ✅ | Merged — SENTINEL APPROVED 96/100 |

### Trade System Hardening
| # | Task | Status | Notes |
|---|---|---|---|
| P2 | Risk-before-execution, dedup, restart/restore correctness | ✅ | Merged — SENTINEL APPROVED |
| P3 | Capital guardrails & structured blocking outcomes | ✅ | Merged — SENTINEL APPROVED 97/100 |
| P4 | Runtime observability & trace propagation | ✅ | Merged |

### Telegram UI
| # | Task | Status | Notes |
|---|---|---|---|
| TG-1 | Market title canonicalization in execution→Telegram path | ✅ | Merged |
| TG-2 | Open positions visibility (full card rendering) | ✅ | Merged |
| TG-3 | Trade history (newest-first, capped display) | ✅ | Merged |
| TG-4 | Menu structure & market scope control | ✅ | Merged — SENTINEL 96/100 |
| TG-5 | Scope state persistence & category inference hardening | ✅ | Merged |
| TG-6 | Premium navigation / UX consolidation | ✅ | Merged |
| TG-7 | Trade lifecycle alerts & scan presence | ✅ | Merged |
| TG-8 | UI text leakage audit | ✅ | Merged |

---

## 🚧 Phase 2 — Platform Foundation
**Goal:** Extract legacy core into a protected kernel, build platform shell, establish multi-user DB schema, and introduce execution isolation boundary.
**Status:** 🚧 In Progress
**Last Updated:** 2026-04-11

> ⚠️ NOTE: PR #396 (`ExecutionIsolationGateway`) is Phase 2 work — branch was named "Phase 3" but correctly belongs here. Review fix pass in progress before merge.

### Core Extraction & Isolation
| # | Task | Status | Notes |
|---|---|---|---|
| 2.1 | Freeze legacy core behavior (no logic drift) | 🚧 | PR #394 merged — core stable but not formally tagged |
| 2.2 | Extract core module boundaries (`core/strategy`, `core/risk`, `core/execution`) | 🚧 | Structure exists, formal boundary not yet declared |
| 2.3 | Add `ExecutionIsolationGateway` — single authoritative mutation boundary | 🚧 | PR #396 open — review fix pass in progress |
| 2.4 | Preserve resolver/bridge purity (read-only attach/resolve) | 🚧 | PR #396 — context_bridge audit suppression included |
| 2.5 | Regression tests around execution path (no breakage on core) | 🚧 | Covered in PR #396 test suite |

### Platform Shell
| # | Task | Status | Notes |
|---|---|---|---|
| 2.6 | Create platform folder structure (`platform/gateway`, `accounts`, `wallet_auth`) | ❌ | Not started |
| 2.7 | Build public API/app gateway skeleton | ❌ | Not started |
| 2.8 | Add legacy-core facade adapter (platform calls into protected core) | ❌ | Not started |
| 2.9 | Add dual-mode routing (legacy path + platform path) | ❌ | Not started |
| 2.10 | Staging deploy for skeleton runtime on Fly.io | ❌ | Migration from Railway pending |

### Multi-User DB Schema
| # | Task | Status | Notes |
|---|---|---|---|
| 2.11 | Design multi-user DB schema (users, accounts, wallets, risk, proofs, audit) | ❌ | Not started |
| 2.12 | Add audit/event log schema | ❌ | Not started |
| 2.13 | Add wallet context abstraction (user/account/wallet/mode/funder/auth) | ❌ | Not started |

---

## ❌ Phase 3 — Execution-Safe MVP
**Goal:** Launch execution-safe single-user MVP on Polymarket wallet/auth model with live/paper modes via Telegram.
**Status:** ❌ Not Started
**Target:** Closed Beta Entry Point

| # | Task | Status | Notes |
|---|---|---|---|
| 3.1 | Implement wallet/auth service (L1 bootstrap + L2 lifecycle) | ❌ | |
| 3.2 | Add wallet type + signature type mapping | ❌ | |
| 3.3 | Add per-user auth state tracking (active/expired/revoked/invalid) | ❌ | |
| 3.4 | Extend execution proof with user context (user_id, wallet_id, ttl, nonce) | ❌ | |
| 3.5 | Add idempotent execution submit/cancel/query flow | ❌ | |
| 3.6 | Implement live/paper mode at user context level | ❌ | Paper mode default for beta |
| 3.7 | Add Telegram public wallet overview (`/balance`, `/positions`) | ❌ | |
| 3.8 | Build reconciliation service baseline | ❌ | |
| 3.9 | Add user WebSocket manager | ❌ | |
| 3.10 | Add market WebSocket fanout manager | ❌ | |
| 3.11 | Focused runtime tests for MVP flow (auth → trade → reconcile) | ❌ | |

### Phase 3 Success Metrics
- User auth flow works end-to-end
- Orders cannot cross user context
- User can view wallet + positions in paper/live mode
- Portfolio state converges reliably after fills

---

## ❌ Phase 4 — Multi-User Public Architecture
**Goal:** Scale to 5–10 closed beta users with isolated execution context and operational controls.
**Status:** ❌ Not Started
**Target:** Closed Beta Full

| # | Task | Status | Notes |
|---|---|---|---|
| 4.1 | Implement per-user account binding (runtime tenant isolation) | ❌ | |
| 4.2 | Add strategy subscription model (user chooses enabled strategies) | ❌ | |
| 4.3 | Add per-user risk profiles (conservative / balanced / aggressive) | ❌ | Default: balanced |
| 4.4 | Add risk & permission service (caps, mode, allowed markets) | ❌ | |
| 4.5 | Build execution queue with priorities (Redis-based) | ❌ | |
| 4.6 | Add retry + dead-letter handling | ❌ | |
| 4.7 | Upgrade Telegram public menu structure for platform model | ❌ | |
| 4.8 | Implement notifications service (lifecycle alerts + errors) | ❌ | |
| 4.9 | Build admin dashboard (users, orders, queue, failures) | ❌ | |
| 4.10 | Add audit replay / incident tools | ❌ | |
| 4.11 | Integration/load testing for concurrent users (5–10) | ❌ | |

### Phase 4 Success Metrics
- User isolation enforced in DB and runtime
- Queue handles concurrent users safely
- Limits enforced before execution
- Ops can trace users, orders, and failures

---

## ❌ Phase 5 — Funding UX & Convenience
**Goal:** Add deposit/withdraw convenience layer without touching trading core.
**Status:** ❌ Not Started
**Target:** Post-Beta

| # | Task | Status | Notes |
|---|---|---|---|
| 5.1 | Design funding transaction model (deposit/withdraw state machine) | ❌ | |
| 5.2 | Add deposit UX flow (address + status) | ❌ | |
| 5.3 | Add withdraw UX flow (confirm + cooldown) | ❌ | |
| 5.4 | Implement transaction tracking (confirmation states) | ❌ | |
| 5.5 | Integrate bridge quote provider (convenience only) | ❌ | |
| 5.6 | Add stuck-funding admin tools | ❌ | |
| 5.7 | Extend reconciliation to funding state | ❌ | |
| 5.8 | End-to-end funding tests | ❌ | |

---

## ❌ Phase 6 — Public Launch & Stabilization
**Goal:** Launch safely, monitor aggressively, harden operations after public exposure.
**Status:** ❌ Not Started
**Target:** Public Launch

| # | Task | Status | Notes |
|---|---|---|---|
| 6.1 | Production deploy on Fly.io | ❌ | |
| 6.2 | Alerting and runtime dashboards (queue, latency, failures) | ❌ | |
| 6.3 | Controlled onboarding rollout (staged public release) | ❌ | |
| 6.4 | Monitor execution success rate | ❌ | Target: 99%+ |
| 6.5 | UX iteration pass (friction reduction) | ❌ | |
| 6.6 | Ops incident runbook finalize | ❌ | |
| 6.7 | Documentation publish (user/admin/API) | ❌ | |

---

## 📊 Success Metrics

| Metric | Closed Beta | Public Beta | Launch |
|---|---|---|---|
| Execution success rate | 95% | 98% | 99%+ |
| Reconciliation convergence | <60s | <20s | <10s |
| Telegram portfolio freshness | <30s | <5s | <2s |
| Concurrent supported users | 5–10 | 100+ | 500+ |
| Duplicate execution rate | <1% | <0.2% | <0.1% |
| Tenant isolation incidents | 0 | 0 | 0 |

---

## ⚠️ Risk Mitigation

| Risk | Mitigation | Owner |
|---|---|---|
| Legacy core breaks during migration | Freeze core first, wrap with facade, no direct rewrite | FORGE-X |
| User context leaks across tenants | Tenant-aware proofs, wallet context, audit logs | FORGE-X |
| Duplicate/ghost order submissions | Idempotent execution keys + queue discipline + reconciliation | FORGE-X |
| Auth/session drift | Explicit auth lifecycle state, rebind/re-auth flows | FORGE-X |
| Reconciliation mismatch | Treat reconciliation as source of truth after execution | FORGE-X |
| Queue backlog under concurrency | Priority queues + dead-letter + ops visibility | FORGE-X |
| UI outruns backend truth | Telegram/Web as clients only, never source of truth | FORGE-X |
| Funding complexity bleeds into core | Keep funding as Phase 5 convenience layer only | COMMANDER |

---

## 🔄 COMMANDER Update Instructions

After every completed task or phase milestone, update this file:

1. Change task status: `❌` → `🚧` → `✅`
2. Add Notes (PR number, SENTINEL score, date)
3. Update Phase status header
4. Update `Last Updated` date
5. Update Board Overview table at top
6. Commit with message: `docs: update ROADMAP.md — [task/phase name]`

---

*Crusader — Build. Deploy. Profit. Repeat.*
*Bayue Walker © 2026*
