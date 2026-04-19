# Walker AI Trading Team — Project Roadmap

**Repo:** https://github.com/bayuewalker/walker-ai-team
**Team:** COMMANDER · FORGE-X · SENTINEL · BRIEFER

> **COMMANDER:** Update status fields (`✅` / `` / `❌`) and Last Updated after every merge or phase milestone.
> This file covers all active projects. Add a new project section when a new project starts.

---

## Active Projects

| Project | Platform | Status | Current Phase |
|---|---|---|---|
| Crusader | Polymarket | Active | Phase 8 — Multi-User Foundation |
| TradingView Indicators | TradingView (Pine Script v5) | ❌ Not Started | — |
| MT5 Expert Advisors | MT4/MT5 (MQL5) | ❌ Not Started | — |
| Kalshi Bot | Kalshi | ❌ Not Started | — |

---

# PROJECT: CRUSADER

**Description:** Non-custodial Polymarket trading platform — multi-user, closed beta first.  
**Tech Stack:** Python · FastAPI · PostgreSQL · Redis · Polymarket CLOB API · WebSocket · Polygon · Telegram Bot · Fly.io  
**Status:** In Progress  
**Last Updated:** 2026-04-19 07:22

## Board Overview

| Phase | Name | Status | Target |
|---|---|---|---|
| Phase 1 | Core Hardening | ✅ Done | Internal |
| Phase 2 | Platform Foundation | ✅ Done | Internal |
| Phase 3 | Execution-Safe MVP | ✅ Done | Closed Beta |
| Phase 4 | Execution Formalization & Boundaries | ✅ Done | Internal |
| Phase 5 | Real Execution & Capital System | ✅ Done | Internal |
| Phase 6 | Production Safety & Stabilization | ✅ Done | Public Preparation |
| Phase 7 | Orchestration & Automation Foundation | ✅ Done | Public Activation Orchestration |
| Phase 8 | Multi-User Foundation | 🚧 In Progress | Multi-User Ownership & Tenant Scope |

---

## CrusaderBot — Multi-User Foundation Checklist

**Goal:** Establish truthful backend foundations for user identity, tenant scope, ownership mapping, and scoped storage under `projects/polymarket/polyquantbot/server/`.  
**Status:** 🚧 In Progress  
**Last Updated:** 2026-04-19 07:22

### Scope Lock
- [x] Keep scope on backend multi-user foundations only
- [x] Treat validation as `MAJOR`
- [x] Avoid false claims of full auth/session productization

### Foundation Deliverables
- [x] Add tenant/user scope helpers for ownership boundaries
- [x] Add schema foundations for `user`, `account`, `wallet`, `user_settings`
- [x] Add storage foundations for scoped entities
- [x] Add thin `user`, `account`, and `wallet` service boundaries
- [x] Add minimal testable API routes for future auth/user/account/wallet surfaces
- [x] Add tests for scope and ownership guard behavior
- [x] Add implementation notes in project docs

### Explicit Exclusions
- [x] Full Telegram auth UX
- [x] Full web auth flow
- [x] Production-grade session system
- [x] Full wallet lifecycle rollout
- [x] Full RBAC and notification system

---

## CrusaderBot — Fly.io Deploy Readiness Checklist

**Goal:** Prepare CrusaderBot for Fly.io deployment while keeping the project rooted at `projects/polymarket/polyquantbot/` and aligning the structure toward the Crusader multi-user blueprint.  
**Status:** In Progress  
**Last Updated:** 2026-04-19 11:45

### Scope Lock
- [x] Keep the working root at `projects/polymarket/polyquantbot/`
- [x] Use `CrusaderBot` as the runtime-facing product name
- [x] Keep the task scoped to deploy-readiness + structural cleanup
- [x] Keep the folder name `polyquantbot` for now
- [x] Treat validation as `MAJOR`
- [x] Require SENTINEL before merge

### Baseline Audit
- [x] Read `PROJECT_STATE.md`
- [x] Read `ROADMAP.md`
- [x] Inspect `projects/polymarket/polyquantbot/` structure
- [x] Confirm deploy artifacts exist:
  - [x] `projects/polymarket/polyquantbot/Dockerfile`
  - [x] `projects/polymarket/polyquantbot/fly.toml`
- [x] Inspect current primary runtime entrypoint:
  - [x] `projects/polymarket/polyquantbot/main.py`
- [x] Confirm the current structure is still polyquantbot-centric
- [x] Confirm the current structure is not yet aligned with the Crusader multi-user blueprint
- [x] Confirm `main.py` is oversized and acting as an orchestration sink
- [x] Confirm overlapping / mixed layers exist:
  - [x] `api`
  - [x] `interface`
  - [x] `telegram`
  - [x] `ui`
  - [x] `views`
  - [x] `legacy`
- [ ] Inventory active import paths that must remain compatible
- [ ] Inventory legacy-only modules
- [ ] Inventory Fly-critical versus optional runtime surfaces

### Target Structure Planning
- [x] Define target structural direction:
  - [x] `client/telegram/`
  - [x] `client/web/`
  - [x] `server/api/`
  - [x] `server/services/`
  - [x] `server/utils/`
  - [x] `configs/`
  - [x] `scripts/`
- [x] Confirm cleanup strategy is structural normalization, not a rewrite
- [x] Confirm `main.py` should become a thin bootstrap or compatibility shim
- [x] Confirm Telegram handlers should become thinner
- [x] Confirm FastAPI should become the clear control-plane runtime surface
- [ ] Produce exact mapping from current directories to target directories
- [ ] Decide what moves now vs later
- [ ] Decide what becomes explicit legacy
- [ ] Decide which compatibility shims are required

### Entrypoints and Runtime Surfaces
- [ ] Create `projects/polymarket/polyquantbot/server/main.py`
- [ ] Create `projects/polymarket/polyquantbot/client/telegram/bot.py`
- [ ] Create `projects/polymarket/polyquantbot/scripts/run_api.py`
- [ ] Create `projects/polymarket/polyquantbot/scripts/run_bot.py`
- [ ] Create `projects/polymarket/polyquantbot/scripts/run_worker.py`
- [ ] Reduce root `main.py` to a thin compatibility wrapper if needed
## CrusaderBot — Fly.io Deploy Readiness Checklist

**Goal:** Prepare CrusaderBot for Fly.io deployment while keeping the project rooted at `projects/polymarket/polyquantbot/` and aligning the structure toward the Crusader multi-user blueprint in `docs/crusader_multi_user_architecture_blueprint.md`.  
**Status:** ✅ Done  
**Last Updated:** 2026-04-19 07:05

### Scope Lock
- [x] Keep the working root at `projects/polymarket/polyquantbot/`
- [x] Use `CrusaderBot` as the runtime-facing product name
- [x] Keep the task scoped to deploy-readiness + structural cleanup
- [x] Keep the folder name `polyquantbot` for now
- [x] Treat validation as `MAJOR`
- [x] Require SENTINEL before merge

### Baseline Audit
- [x] Read `PROJECT_STATE.md`
- [x] Read `ROADMAP.md`
- [x] Inspect `projects/polymarket/polyquantbot/` structure
- [x] Confirm deploy artifacts exist:
  - [x] `projects/polymarket/polyquantbot/Dockerfile`
  - [x] `projects/polymarket/polyquantbot/fly.toml`
- [x] Inspect current primary runtime entrypoint:
  - [x] `projects/polymarket/polyquantbot/main.py`
- [x] Confirm the current structure is still polyquantbot-centric
- [x] Confirm the current structure is not yet aligned with the Crusader multi-user blueprint
- [x] Confirm `main.py` is oversized and acting as an orchestration sink
- [x] Confirm overlapping / mixed layers exist:
  - [x] `api`
  - [x] `interface`
  - [x] `telegram`
  - [x] `ui`
  - [x] `views`
  - [x] `legacy`
- [ ] Inventory active import paths that must remain compatible
- [ ] Inventory legacy-only modules
- [ ] Inventory Fly-critical versus optional runtime surfaces

### Target Structure Planning
- [x] Define target structural direction from the Crusader multi-user blueprint:
  - [x] `client/telegram/`
  - [x] `client/web/`
  - [x] `server/api/`
  - [x] `server/services/`
  - [x] `server/utils/`
  - [x] `configs/`
  - [x] `scripts/`
- [x] Confirm cleanup strategy is structural normalization, not a rewrite
- [x] Confirm `main.py` should become a thin bootstrap or compatibility shim
- [x] Confirm Telegram handlers should become thinner
- [x] Confirm FastAPI should become the clear control-plane runtime surface
- [x] Produce exact mapping from current directories to target directories
- [x] Decide what moves now vs later
- [x] Decide what becomes explicit legacy
- [x] Decide which compatibility shims are required

### Entrypoints and Runtime Surfaces
- [x] Create `projects/polymarket/polyquantbot/server/main.py`
- [x] Create `projects/polymarket/polyquantbot/client/telegram/bot.py`
- [x] Create `projects/polymarket/polyquantbot/scripts/run_api.py`
- [x] Create `projects/polymarket/polyquantbot/scripts/run_bot.py`
- [x] Create `projects/polymarket/polyquantbot/scripts/run_worker.py`
- [ ] Reduce root `main.py` to a thin compatibility wrapper if needed
- [ ] Remove oversized startup responsibility from root `main.py`
- [x] Ensure new entrypoints resolve imports cleanly

### FastAPI Control Plane
- [x] Implement minimal FastAPI app in `server/main.py`
- [x] Add `/health`
- [x] Add `/ready`
- [x] Bind to Fly-injected `PORT`
- [x] Add deterministic startup validation for required env
- [x] Add graceful shutdown behavior
- [x] Make CrusaderBot the runtime-facing app name

### Telegram Bootstrap Cleanup
- [x] Move Telegram bootstrap responsibility into `client/telegram/bot.py`
- [x] Keep Telegram runtime independently launchable
- [ ] Keep Telegram handlers thin
- [ ] Remove deploy-critical logic from Telegram handler layer
- [x] Ensure Telegram runtime does not block the API runtime path

### Fly.io Deployment Contract
- [x] Update `projects/polymarket/polyquantbot/fly.toml`
- [x] Ensure Fly config matches the actual runtime process model
- [x] Ensure internal port matches app binding
- [x] Ensure health check path matches implemented route
- [x] Ensure machine/process command points to the correct entrypoint
- [x] Update `projects/polymarket/polyquantbot/Dockerfile`
- [x] Ensure Docker startup command is coherent
- [x] Ensure no stale command still points at the old monolithic runtime path

### Config, Compatibility, and Proof
- [ ] Define minimum deploy-critical environment variables
- [ ] Separate required vs optional env
- [x] Document what stayed, what moved, and what is now legacy
- [x] Avoid fake abstraction and dead imports
- [x] Add startup/import tests
- [x] Add `/health` test
- [x] Add deploy-critical config validation tests
- [x] Add deploy notes under project docs
- [x] Create a FORGE report under `projects/polymarket/polyquantbot/reports/forge/`
- [x] Update `PROJECT_STATE.md` truthfully when execution starts
- [x] Open PR from `refactor/infra-crusaderbot-fly-readiness-20260419`
- [x] Request SENTINEL review before merge

### Final Acceptance Gate
- [x] Runtime-facing name is `CrusaderBot`
- [x] Project remains under `projects/polymarket/polyquantbot/`
- [x] Fly.io deploy surface is real and coherent
- [x] FastAPI health path works
- [x] Entrypoints are cleaner than baseline
- [x] Structure is materially closer to the Crusader blueprint
- [x] No fake abstraction introduced
- [x] FORGE report exists
- [x] State files are truthful
- [x] PR is ready for COMMANDER + SENTINEL

---

## Phase 6 — Production Safety & Stabilization

**Goal:** Ensure production-grade safety, stability, and operational truth.  
**Status:** ✅ Done  
**Last Updated:** 2026-04-18 22:26

| Sub-Phase | Name | Status | Notes |
|---|---|---|---|
| 6.1 | Execution Ledger (In-Memory) | ✅ Done | Deterministic append-only records and read-only reconciliation delivered. |
| 6.2 | Persistent Ledger & Audit Trail | ✅ Done | Append-only local-file persistence and deterministic reload delivered. |
| 6.3 | Kill Switch & Execution Halt Foundation | ✅ Done | Merged via PR #479 and preserved as approved carry-forward truth. |
| 6.4.1 | Monitoring & Circuit Breaker FOUNDATION Implementation | ✅ Done | Merged via PR #572 with deterministic contract in `monitoring/foundation.py`. |
| 6.4.2 | Runtime Monitoring Narrow Integration | ✅ Done | Merged truth preserved for `ExecutionTransport.submit_with_trace` narrow integration after SENTINEL APPROVED (95/100). |
| 6.4.3 | Authorizer-Path Monitoring Narrow Integration | ✅ Done | Merged via PR #491. SENTINEL APPROVED (99/100). Narrow scope preserved: `LiveExecutionAuthorizer.authorize_with_trace` + `ExecutionTransport.submit_with_trace` only. |
| 6.4.4 | Gateway-Path Monitoring Narrow Integration Expansion | ✅ Done | Runtime/code path merged via PR #493. SENTINEL APPROVED validation path recorded in PR #495 (97/100). Accepted narrow three-path execution monitoring baseline preserved. |
| 6.4.5 | Exchange-Path Monitoring Narrow Integration Expansion | ✅ Done | Merged truth confirmed after PR #497 and PR #498 at declared narrow scope. Explicit exclusions preserved. |
| 6.4.6 | Signing-Boundary Monitoring Narrow Integration Expansion | ✅ Done | Merged-main truth confirmed after PR #501 and PR #502 at declared narrow scope. Explicit exclusions preserved. |
| 6.4.7 | Capital-Boundary Monitoring Narrow Integration Expansion | ✅ Done | Merged-main truth confirmed after PR #504 and PR #505 at declared narrow scope. Explicit exclusions preserved. |
| 6.4.8 | Settlement-Boundary Monitoring Narrow Integration Expansion | ✅ Done | Merged-main truth accepted for narrow settlement boundary at `FundSettlementEngine.settle_with_trace` with deterministic ALLOW/BLOCK/HALT monitoring decisions. |
| 6.4.9 | Orchestration-Entry Monitoring Narrow Integration Expansion | ✅ Done | Merged-main truth accepted for narrow orchestration-entry boundary at `ExecutionActivationGate.evaluate_with_trace` with deterministic ALLOW/BLOCK/HALT monitoring decisions. |
| 6.4.10 | Adapter-Boundary Monitoring Narrow Integration Expansion | ✅ Done | Merged-main truth accepted after PR #513 and PR #514 at declared narrow scope. |
| 6.5.1 | Wallet Lifecycle Foundation — Secret Loading Contract | ✅ Done | Merged-main accepted truth at `WalletSecretLoader.load_secret` with ownership + activation constraints and no plaintext secret output. |
| 6.5.2 | Wallet Lifecycle Foundation — State/Storage Boundary Contract | ✅ Done | Merged-main accepted truth after PR #524 at `WalletStateStorageBoundary.store_state`. |
| 6.5.3 | Wallet Lifecycle Foundation — State Read Boundary Narrow Slice | ✅ Done | Merged-main accepted truth after PR #536 at `WalletStateStorageBoundary.read_state`. |
| 6.5.4 | Wallet Lifecycle Foundation — State Clear Boundary Narrow Slice | ✅ Done | Merged-main accepted truth after PR #537 at `WalletStateStorageBoundary.clear_state`. |
| 6.5.5 | Wallet Lifecycle Foundation — State Exists Boundary Narrow Slice | ✅ Done | Merged-main accepted truth after PR #539 at `WalletStateStorageBoundary.has_state`. |
| 6.5.6 | Wallet Lifecycle Foundation — State List Metadata Boundary Narrow Slice | ✅ Done | Merged-main accepted truth after PR #541 at `WalletStateStorageBoundary.list_state_metadata`. |
| 6.5.7 | Wallet Lifecycle Foundation — State Metadata Query Expansion | ✅ Done | Merged-main truth accepted via PR #543 at `WalletStateStorageBoundary.list_state_metadata`. |
| 6.5.8 | Wallet Lifecycle Foundation — State Metadata Exact Lookup | ✅ Done | Merged-main truth accepted via PR #544 at `WalletStateStorageBoundary.get_state_metadata`. |
| 6.5.9 | Wallet Lifecycle Foundation — State Metadata Exact Batch Lookup | ✅ Done | Merged-main truth accepted via PR #546 at `WalletStateStorageBoundary.get_state_metadata_batch`. |
| 6.5.10 | Wallet Lifecycle Foundation — State Exact Batch Read Boundary | ✅ Done | Merged-main truth accepted via PR #557 at `WalletStateStorageBoundary.read_state_batch`. |
| 6.6.1 | Wallet Lifecycle State Reconciliation Foundation | ✅ Done | Merged-main truth accepted via PR #558 at `WalletLifecycleReconciliationBoundary.reconcile_wallet_state`. |
| 6.6.2 | Wallet Lifecycle Batch Reconciliation | ✅ Done | Merged-main truth accepted via PR #559 at `WalletLifecycleReconciliationBoundary.reconcile_wallet_state_batch`. |
| 6.6.3 | Wallet Reconciliation Mutation Correction Foundation | ✅ Done | Merged-main truth accepted via PR #560 at `WalletReconciliationCorrectionBoundary.apply_correction`. |
| 6.6.4 | Wallet Reconciliation Retry/Worker Foundation | ✅ Done | Merged-main truth accepted via PR #561 at `WalletReconciliationRetryWorkerBoundary.decide_retry_work_item`. |
| 6.6.5 | Public Readiness Slice Opener Foundation | ✅ Done | Merged via PR #562 with deterministic go/hold/blocked readiness evaluation contract. |
| 6.6.6 | Public Activation Gate Foundation | ✅ Done | Merged via PR #563 with deterministic allowed/denied_hold/denied_blocked gate outcomes. |
| 6.6.7 | Minimal Public Activation Flow Foundation | ✅ Done | Merged via PR #564 with deterministic completed/stopped_hold/stopped_blocked thin flow routing. |
| 6.6.8 | Public Safety Hardening | ✅ Done | Merged via PR #565 with deterministic cross-boundary consistency pass/hold/blocked hardening outcomes. |
| 6.6.9 | Minimal Execution Hook | ✅ Done | Merged via PR #566 with deterministic executed/stopped_hold/stopped_blocked hook outcomes. |

---

## Phase 7 — Orchestration & Automation Foundation

**Goal:** Add thin deterministic orchestration contracts over the completed 6.6 baseline without broad automation rollout.  
**Status:** In Progress  
**Last Updated:** 2026-04-19 04:15

| Sub-Phase | Name | Status | Notes |
|---|---|---|---|
| 7.0 | Orchestration and Automation Foundation (Single Public Cycle) | ✅ Done | Deterministic single-cycle orchestration entrypoint `run_public_activation_cycle` merged and preserved as thin synchronous chaining over 6.6.5 -> 6.6.6 -> 6.6.7 -> 6.6.8 -> 6.6.9. |
| 7.1 | Public Activation Trigger Surface (Single Entrypoint) | ✅ Done | Merged with one synchronous CLI trigger path invoking `run_public_activation_cycle(...)` and explicit completed/stopped_hold/stopped_blocked mapping. |
| 7.2 | Lightweight Automation Scheduler (Single Invocation Cycle) | ✅ Done | Deterministic triggered/skipped/blocked result categories delivered; blocked(`invalid_contract`) for negative quota; one synchronous invocation cycle only. |
| 7.3 | Runtime Auto-Run Loop Foundation (Bounded Synchronous Loop) | ✅ Done | Finalized as merged-main truth with preserved bounded synchronous loop behavior over the 7.2 scheduler boundary and unchanged loop result categories. |
| 7.4 | Observability / Visibility Foundation | ✅ Done | Merged to main. Deterministic visibility records (visible/partial/blocked) over Phase 6.4.1 monitoring evaluations, Phase 7.2 scheduler decisions, and Phase 7.3 loop outcomes in `monitoring/observability_foundation.py`; 45 passing tests. |
| 7.5 | Operator Control / Manual Override | ✅ Done | Merged to main via PR #575. Deterministic `OperatorControlDecision` injected before Phase 7.2 scheduler decision and Phase 7.3 loop continuation. |
| 7.6 | State Persistence / Execution Memory Foundation | ✅ Done | Completed baseline preserved in `core/execution_memory_foundation.py` with deterministic local-file load/store/clear boundary for minimal last-run context and explicit invalid_contract blocked behavior. |
| 7.7 | Recovery / Resume Foundation | ✅ Done | Merged via PR #577. Deterministic `force_block -> blocked`, `hold -> restart_fresh`, and closed terminal loop outcomes (`completed`/`stopped_hold`/`exhausted`) -> `restart_fresh` over Phase 7.6 execution memory only. |

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
-  = In Progress
- ❌ = Not Started

### Update Triggers

| Event | Action |
|---|---|
| FORGE-X PR merged | Task `❌` / `` → `✅`, add PR # and date in notes |
| SENTINEL APPROVED | Confirm status truthfully and add score in notes when relevant |
| Phase complete | Update phase header and Active Projects table |
| New task scoped | Add row with `❌` or `` as appropriate |
| New project activated | Fill phases/tasks and update Active Projects table |

### Commit Format
`docs: update ROADMAP.md — [project] [task or phase name]`
