# Walker AI Trading Team — Project Roadmap

**Repo:** https://github.com/bayuewalker/walker-ai-team
**Team:** COMMANDER · FORGE-X · SENTINEL · BRIEFER

> **COMMANDER:** Update status fields (`✅` / `🚧` / `❌`) and Last Updated after every merge or phase milestone.
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
**Last Updated:** 2026-04-19 14:01

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
| Phase 8 | Multi-User Foundation | 🚧 In Progress | Multi-User Ownership + Auth/Session Scope |

---

## CrusaderBot — Multi-User Foundation Checklist

**Goal:** Establish truthful backend foundations for user identity, tenant scope, ownership mapping, and scoped storage under `projects/polymarket/polyquantbot/server/`.  
**Status:** ✅ Done (Phase 8.1 merged via PR #590)  
**Last Updated:** 2026-04-19 10:04

## Scope Lock
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

## CrusaderBot — Auth/Session Foundation Checklist (Phase 8.2)

**Goal:** Add truthful auth/session foundation primitives that derive trusted tenant/user scope for backend routes under `projects/polymarket/polyquantbot/server/`.  
**Status:** ✅ Done (Merged baseline; post-merge truth synced)  
**Last Updated:** 2026-04-19 10:04

### Scope Lock
- [x] Keep scope on backend auth/session foundation only
- [x] Treat validation as `MAJOR`
- [x] Avoid false claims of full auth productization

### Foundation Deliverables
- [x] Add auth/session identity and scope schemas
- [x] Add trusted scope derivation primitive over active session context
- [x] Add minimal auth/session service + in-memory session storage boundary
- [x] Add FastAPI dependency for authenticated scope injection
- [x] Integrate authenticated scope into minimal `/foundation` route behavior
- [x] Add tests for trusted scope derivation and protected wallet route behavior
- [x] Update implementation notes for lane 8.2

### Explicit Exclusions
- [x] Full Telegram login flow
- [x] Full web login UX
- [x] OAuth rollout
- [x] Production token rotation platform
- [x] Full RBAC system
- [x] Delegated wallet signing lifecycle
- [x] Database migration rollout

---

## CrusaderBot — Persistent Session Storage Foundation Checklist (Phase 8.3)

**Goal:** Replace in-memory-only auth/session continuity with a truthful persistent session storage boundary for restart-safe identity scope under `projects/polymarket/polyquantbot/server/`.  
**Status:** ✅ Done (Merged via PR #596)  
**Last Updated:** 2026-04-19 11:10

### Scope Lock
- [x] Keep scope on persistent auth/session foundation only
- [x] Treat validation as `MAJOR`
- [x] Avoid false claims of full production auth

### Foundation Deliverables
- [x] Introduce persistent session storage boundary with deterministic local-file persistence
- [x] Integrate `AuthSessionService` session reads/writes to persistent storage
- [x] Support minimal session lifecycle transitions (`active`, `revoked`, `expired` enforcement)
- [x] Keep trusted-scope derivation contract unchanged for protected foundation routes
- [x] Add revoke endpoint for truthful invalidation behavior
- [x] Add tests for persisted readback, restart continuity, revoked rejection, and expired rejection
- [x] Update implementation notes and state truth for lane 8.3

### Explicit Exclusions
- [x] Full Telegram login UX
- [x] Full web login UX
- [x] OAuth rollout
- [x] Production token rotation platform
- [x] Full RBAC
- [x] Delegated wallet signing lifecycle
- [x] Full DB migration platform
- [x] Broad wallet lifecycle rollout

---

## CrusaderBot — Client Auth Handoff / Wallet-Link Foundation Checklist (Phase 8.4)

**Goal:** Establish truthful client-to-backend identity handoff and user-owned wallet-link foundation over the persistent session backbone under `projects/polymarket/polyquantbot/server/`.  
**Status:** ✅ Done (Merged via PR #598. SENTINEL CONDITIONAL gate satisfied. Pytest gate: 25/25 pass. Evidence: `projects/polymarket/polyquantbot/reports/forge/phase8-4_02_pytest-evidence-pass.md`)  
**Last Updated:** 2026-04-19 11:28

### Scope Lock
- [x] Keep scope on client auth handoff contract + wallet-link foundation only
- [x] Treat validation as `MAJOR`
- [x] Avoid false claims of full public auth or full wallet lifecycle completion

### Foundation Deliverables
- [x] Add minimal client auth handoff contract with structural validation (core/client_auth_handoff.py)
- [x] Expose POST /auth/handoff route — issues session for known user via handoff claim
- [x] Add wallet-link schema foundation (WalletLinkRecord, WalletLinkCreateRequest)
- [x] Add wallet-link storage boundary (WalletLinkStore — in-memory)
- [x] Add wallet-link service (create_link, list_links — user-scoped)
- [x] Expose authenticated POST /auth/wallet-links and GET /auth/wallet-links routes
- [x] Enforce authenticated scope on all wallet-link routes (no session → 403)
- [x] Enforce cross-user isolation (user B cannot read user A's wallet-links)
- [x] Wire WalletLinkStore + WalletLinkService + client_auth_router into server/main.py
- [x] Add 12 tests covering handoff contract, handoff route, wallet-link create/read/deny flows
- [x] Update forge report, PROJECT_STATE.md, ROADMAP.md

### Explicit Exclusions
- [x] Full Telegram login UX
- [x] Full web login UX
- [x] OAuth rollout
- [x] Production token rotation platform
- [x] Full RBAC
- [x] Delegated signing lifecycle
- [x] Full wallet lifecycle orchestration
- [x] Exchange signing rollout
- [x] On-chain settlement rollout
- [x] Persistent wallet-link storage (deferred follow-up lane)
- [x] Broad portfolio engine work

---

## CrusaderBot — Persistent Wallet-Link Storage / Lifecycle Foundation Checklist (Phase 8.5)

**Goal:** Replace in-memory-only wallet-link records with restart-safe persistent storage and add minimal truthful wallet-link lifecycle controls under `projects/polymarket/polyquantbot/server/`.  
**Status:** ✅ Done (merged. Pytest gate: 33/33 pass. Evidence: `projects/polymarket/polyquantbot/reports/forge/phase8-5_01_persistent-wallet-link-foundation.md`, `projects/polymarket/polyquantbot/reports/forge/phase8-5_02_pytest-evidence-pass.md`. SENTINEL: `projects/polymarket/polyquantbot/reports/sentinel/phase8-5_01_wallet-link-persistence-validation.md`)  
**Last Updated:** 2026-04-19 12:12

### Scope Lock
- [x] Keep scope on persistent wallet-link storage + minimal lifecycle foundation only
- [x] Treat validation as `MAJOR`
- [x] Avoid false claims of full wallet lifecycle completion or production orchestration

### Foundation Deliverables
- [x] Introduce `PersistentWalletLinkStore` with deterministic local-file JSON persistence (atomic overwrite)
- [x] Convert `WalletLinkStore` to abstract base class (SessionStore pattern)
- [x] Switch `server/main.py` off in-memory `WalletLinkStore` to `PersistentWalletLinkStore`
- [x] Add `CRUSADER_WALLET_LINK_STORAGE_PATH` env var for configurable storage path
- [x] Add `set_link_status` lifecycle method to storage boundary
- [x] Add `unlink_link` method to `WalletLinkService` (ownership-enforced `active` → `unlinked`)
- [x] Expose `PATCH /auth/wallet-links/{link_id}/unlink` authenticated route
- [x] Add tests for persisted readback, restart-safe continuity, unlink behavior, cross-user isolation
- [x] Update forge report, PROJECT_STATE.md, ROADMAP.md

### Explicit Exclusions
- [x] Full wallet lifecycle orchestration
- [x] Delegated signing lifecycle
- [x] Exchange signing rollout
- [x] On-chain settlement rollout
- [x] Full RBAC
- [x] OAuth rollout
- [x] Production token rotation platform
- [x] Broad portfolio engine work
- [x] Full database migration platform

---

## CrusaderBot — Persistent Multi-User Store Foundation Checklist (Phase 8.6)

**Goal:** Replace in-memory-only user/account/wallet ownership records with restart-safe persistent storage under `projects/polymarket/polyquantbot/server/`, preserving strict tenant/user/account/wallet ownership semantics established in earlier phases.  
**Status:** ✅ Done (merged. Pytest gate: 46/46 pass. Evidence: `projects/polymarket/polyquantbot/reports/forge/phase8-6_01_persistent-multi-user-store-foundation.md`, `projects/polymarket/polyquantbot/reports/forge/phase8-6_02_pytest-evidence-pass.md`. SENTINEL CONDITIONAL gate satisfied.)  
**Last Updated:** 2026-04-19 12:58

### Scope Lock
- [x] Keep scope on persistent user/account/wallet store foundation only
- [x] Treat validation as `MAJOR`
- [x] Avoid false claims of full database rollout or production orchestration

### Foundation Deliverables
- [x] Introduce `MultiUserStore` abstract base class (`server/storage/multi_user_store.py`)
- [x] Introduce `MultiUserStoreError` typed exception
- [x] Introduce `PersistentMultiUserStore` with deterministic local-file JSON persistence (atomic overwrite)
- [x] Extend `InMemoryMultiUserStore` to implement `MultiUserStore` (zero regression)
- [x] Switch `UserService`, `AccountService`, `WalletService`, `AuthSessionService` off `InMemoryMultiUserStore` type hint to `MultiUserStore`
- [x] Wire `PersistentMultiUserStore` into `server/main.py` (replaces in-memory store)
- [x] Add `CRUSADER_MULTI_USER_STORAGE_PATH` env var (default: `/tmp/crusaderbot/runtime/multi_user.json`)
- [x] Add tests for persisted user/account/wallet readback, restart-safe ownership chain, cross-user isolation regression
- [x] Update forge report, PROJECT_STATE.md, ROADMAP.md

### Explicit Exclusions
- [x] Full database migration platform
- [x] Full portfolio engine
- [x] Exchange execution changes
- [x] On-chain settlement changes
- [x] RBAC
- [x] OAuth
- [x] Delegated signing lifecycle
- [x] Full wallet lifecycle orchestration

---

## CrusaderBot — Telegram/Web Runtime Handoff Integration Foundation Checklist (Phase 8.7)

**Goal:** Connect real client runtime entry surfaces (Telegram bot + web) to the persistent backend identity/session/ownership foundation established in Phases 8.1–8.6, enabling truthful authenticated handoff/session creation from client runtimes.  
**Status:** ✅ Done (merged. SENTINEL CONDITIONAL gate satisfied. Pytest gate: 62/62 pass. Evidence: `projects/polymarket/polyquantbot/reports/forge/phase8-7_01_telegram-web-runtime-handoff-foundation.md`, `projects/polymarket/polyquantbot/reports/forge/phase8-7_02_pytest-evidence-pass.md`. SENTINEL: `projects/polymarket/polyquantbot/reports/sentinel/phase8-7_01_runtime-handoff-validation-pr604.md`)  
**Last Updated:** 2026-04-19 14:01

### Scope Lock
- [x] Keep scope on Telegram/Web client runtime handoff surfaces only
- [x] Treat validation as `MAJOR`
- [x] Avoid false claims of full polished Telegram or web UX completion

### Foundation Deliverables
- [x] Add `CrusaderBackendClient` — thin async HTTP client bridging client runtimes to backend `/auth/handoff`
- [x] Add `client/telegram/handlers/auth.py` — thin `/start` handler with `handle_start()` dispatching handoff via backend client
- [x] Add `client/web/handoff.py` — minimal web handoff surface with `handle_web_handoff()`
- [x] Update `client/telegram/bot.py` to wire backend client reference into Telegram runtime bootstrap
- [x] Add 12 targeted runtime integration tests covering Telegram/Web handoff path behavior and regressions
- [x] Update forge report, PROJECT_STATE.md, ROADMAP.md

### Explicit Exclusions
- [x] Full polished Telegram product UX
- [x] Full polished web app UX
- [x] OAuth rollout
- [x] RBAC rollout
- [x] Delegated signing lifecycle
- [x] Exchange execution rollout
- [x] Portfolio engine rollout

---

## CrusaderBot — Real Telegram Dispatch Integration Foundation Checklist (Phase 8.8)

**Goal:** Wire the Telegram runtime to a real dispatchable `/start` path over the existing `handle_start()` foundation. Introduce a truthful command dispatch boundary (`TelegramDispatcher`) that routes `/start` to `handle_start()` and maps `HandleStartResult` to a typed `DispatchResult`. Update `client/telegram/bot.py` to wire the dispatcher truthfully. Exclude full polished Telegram UX, broad command suite, OAuth, RBAC, and delegated signing lifecycle.  
**Status:** 🚧 In Progress — SENTINEL validation required before merge  
**Last Updated:** 2026-04-19 14:01

### Scope Lock
- [x] Keep scope on Telegram command dispatch boundary only (/start → handle_start)
- [x] Treat validation as `MAJOR`
- [x] Avoid false claims of full polished Telegram bot product

### Foundation Deliverables
- [x] Add `TelegramCommandContext` — inbound command context dataclass
- [x] Add `DispatchResult` — typed dispatch result with outcome + reply_text + session_id
- [x] Add `TelegramDispatcher` — routes /start to handle_start(), handles unknown commands safely
- [x] Update `client/telegram/bot.py` to wire `TelegramDispatcher` over backend client
- [x] Add targeted tests for /start dispatch, reply mapping, and unknown command handling
- [x] Preserve Phase 8.7 regression suite (62/62 pass carried forward)
- [x] Update forge report, PROJECT_STATE.md, ROADMAP.md

### Explicit Exclusions
- [x] Full polished Telegram UX
- [x] Broad command suite beyond /start
- [x] OAuth rollout
- [x] RBAC rollout
- [x] Delegated signing lifecycle
- [x] Exchange execution rollout
- [x] Portfolio engine rollout
- [x] Full web UX rollout

---

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
`docs: update ROADMAP.md — [project] [task or phase name]`
