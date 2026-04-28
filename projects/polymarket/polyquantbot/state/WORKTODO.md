## CrusaderBot Work Checklist

### From Now to Finish

---

## PRIORITY 1 — Bot Public-Ready Baseline

This must be finished first.

### Status Snapshot (2026-04-23)

#### DONE / Mostly Done

- [x] Fly app is alive
- [x] Telegram runtime is active on Fly
- [x] Telegram startup is automatic in the deploy path
- [x] `/ready` includes Telegram runtime truth
- [x] `/start` replies on deployed environment
- [x] Onboarding/public-safe/paper-only copy refined
- [x] Fallback/error copy refined
- [x] Monitor Integration + Observability Hardening lane closed on main
- [x] Phase 10.2 public-safe command expansion lane closed on main (PR #713 merged truth)

#### Latest merged truth (2026-04-23 14:15 Asia/Jakarta)

- Public Telegram copy layer is consolidated through shared presentation helpers in `client/telegram/presentation.py` so `/start`, onboarding-required, onboarding-started, linked/active-session variants, temporary backend/runtime issues, and unknown-command fallback share one structure.
- `/help` and `/status` keep a consistent boundary block with the same public paper-beta posture and no live-trading/production-capital readiness overclaim.
- Live Telegram baseline evidence is recorded in `projects/polymarket/polyquantbot/reports/forge/telegram_runtime_05_priority1-live-proof.md` with supporting log in `projects/polymarket/polyquantbot/reports/forge/telegram_runtime_05_priority1-live-proof.log`.
- Verified from live runtime evidence: `/start`, `/help`, `/status`, and unknown-command fallback all returned non-empty/non-dummy responses.
- Public baseline path showed no silent fail behavior during the verified command checks.
- Paper-only public-safe boundary remained visible in live replies; no live-trading or production-capital readiness claim is introduced.
- Remaining debt is unchanged: repeated `/start` progression flow still feels stepwise and should be refined further without expanding runtime activation scope.

### 2. Baseline Public Commands

- [x] Make sure responses are not empty or dummy
- [x] Make sure there is no timeout or silent failure

### 3. Path to Public Telegram UX Refinement

- [ ] Refine the existing Telegram onboarding flow
- [x] Refine the existing Telegram command UX
- [x] Refine the current welcome intro for new users
- [x] Refine the current help and status copy
- [x] Refine paper-only messaging across the existing Telegram flow
- [x] Refine the next-step guidance for new users
- [x] Refine the unlinked-user flow using the current foundation
- [x] Refine the linked-user flow using the current foundation
- [x] Refine fallback and error messaging
- [x] Refine Telegram formatting and readability

### 4. Public Command Set

- [x] Keep the existing public command baseline clean and useful
- [x] Prepare `/paper`
- [x] Prepare `/about`
- [x] Prepare `/risk_info` (public informational command)
- [x] Prepare `/account` and `/link`
- [x] Keep `/risk` limited to runtime/operator path (not public-safe command baseline)
- [x] Separate public commands from admin/operator commands
- [x] Hide commands that are not ready yet

### 5. Public-Safe Boundaries

- [x] Do not claim live trading readiness
- [x] Do not claim production-capital readiness
- [x] Keep the paper-only boundary visible everywhere
- [x] Guard admin/internal paths properly

### 6. Observability Baseline

- [x] Add bot startup logs
- [x] Add command received logs
- [x] Add command handled logs
- [x] Add reply success/failure logs
- [x] Add missing env / disabled mode logs
- [x] Add Sentry Python runtime initialization + exception capture guardrails (env-only `SENTRY_DSN`, FastAPI + Telegram/runtime exception surfaces)

### 7. End-to-End Validation

- [x] Deploy the latest version
- [x] Confirm `/health` is OK
- [x] Confirm `/ready` is OK
- [x] Confirm `/start` is OK
- [x] Confirm `/help` is OK
- [x] Confirm `/status` is OK
- [x] Save validation evidence

Current truth (2026-04-22 02:31 Asia/Jakarta): live baseline command proof now exists for `/start`, `/help`, `/status`, and unknown fallback on deployed runtime; onboarding/session UX repetition on repeated `/start` remains open as follow-up refinement debt only.

### Done Condition

- [x] The bot is truly usable as a public-ready paper bot baseline

---

## PRIORITY 2 — DB, Persistence, and Runtime Hardening

Finish this after the public bot baseline works.

### Status Snapshot (2026-04-24 11:53 Asia/Jakarta)

#### MERGED ON MAIN

- [x] Phase 10.4 / Priority 2 DB readiness/startup hardening closed on main via PR #725 and PR #726
- [x] Phase 10.5 / Priority 2 persistence stabilization baseline closed on main via PR #727 and PR #728
- [x] Phase 10.6 / Priority 2 runtime config + readiness truth hardening closed on main via PR #729 and PR #730
- [x] Phase 10.7 / Priority 2 shutdown/restart/dependency resilience hardening closed on main via PR #731 and PR #732

#### MERGED ON MAIN (latest)

- [x] Phase 10.8 / Priority 2 logging and monitoring hardening closed on main via PR #734, PR #736, and PR #737

#### MERGED ON MAIN (latest security lane closure)

- [x] Phase 10.9 / Priority 2 security baseline hardening closed with final SENTINEL APPROVED gate for PR #742 (59-pass targeted rerun + exact branch-truth sync)

#### MERGED ON MAIN (Deployment Hardening lane closure)

- [x] Deployment Hardening lane closed: PR #759 merged to main on 2026-04-24 11:21 Asia/Jakarta by COMMANDER (SENTINEL APPROVED 98/100, zero critical issues)
- [x] Clean up the Dockerfile
- [x] Keep `fly.toml` in sync
- [x] Define restart policy clearly
- [x] Define rollback strategy clearly
- [x] Define post-deploy smoke tests clearly

### 9. Supabase / Postgres Integration Hardening

- [x] Finalize a stable `DATABASE_URL`
- [x] Make sure `sslmode=require` is used where needed
- [x] Confirm pooled connection strategy
- [x] Add DB health checks
- [x] Make sure startup does not fail when DB is slow

### 10. Persistence Stabilization

- [x] Audit any state still stored in files or temp storage
- [x] Move critical user/session state into DB
- [x] Move link/account state into DB
- [x] Remove split-brain state between file storage and DB
- [x] Make sure restart/redeploy does not break state

### 11. Runtime Config Hardening

- [x] Validate required env vars at boot
- [x] Make missing-secret errors clear
- [x] Reduce unsafe defaults
- [x] Make startup config summary safe and truthful

### 12. Health / Readiness Truth Hardening

- [x] Make `/health` check the main process properly
- [x] Make `/ready` check relevant dependencies properly
- [x] Include Telegram runtime state in readiness
- [x] Include DB state in readiness
- [x] Remove false green status

### 13. Error Handling and Resilience

- [x] Make graceful shutdown work properly
- [x] Make restart safety reliable
- [x] Prevent worker crash from corrupting state
- [x] Add retry handling for non-fatal dependencies

### 14. Logging and Monitoring Hardening

- [x] Keep structured logging consistent
- [x] Improve startup logs
- [x] Make error traces easy to follow
- [x] Prepare minimum viable monitoring

### 15. Security Baseline (DONE)

- [x] Make sure secrets never appear in logs
- [x] Remove any hardcoded credentials
- [x] Protect admin access properly
- [x] Restrict sensitive routes

### 16. Deployment Hardening

- [x] Clean up the Dockerfile
- [x] Keep `fly.toml` in sync
- [x] Define restart policy clearly
- [x] Define rollback strategy clearly
- [x] Define post-deploy smoke tests clearly

### Done Condition

- [x] The bot is not just running, but stable and persistent

---

## PRIORITY 3 — Paper Trading Product Completion

Finish this after runtime and persistence are stable.

### 17. Paper Account Model

- [x] Define the paper balance model
- [x] Define paper position tracking
- [x] Define paper PnL tracking
- [x] Add reset/test flow for operators

### 18. Paper Execution Engine

- [x] Define paper order intent flow
- [x] Enable paper entry logic
- [x] Enable paper exit logic
- [x] Make paper fill assumptions clear
- [x] Make paper execution logging clear

### 19. Paper Portfolio Surface

- [x] Show open paper positions
- [x] Show realized PnL
- [x] Show unrealalized PnL
- [x] Show summary through bot/API

### 20. Paper Risk Controls

- [x] Enforce exposure caps
- [x] Enforce drawdown caps
- [x] Enforce kill switch
- [x] Show risk state clearly

### 21. Paper Strategy Visibility

- [x] Show strategy state
- [x] Show signal state
- [x] Show enable/disable visibility
- [x] Show suppressed/blocked reasons

### 22. Admin / Operator Paper Controls

- [x] Show runtime paper summary
- [x] Show readiness paper state
- [x] Add pause/resume if supported
- [x] Keep admin commands separate

### 23. Public Paper UX Completion

- [x] Make sure users understand paper mode
- [x] Show paper product status clearly
- [x] Show product limitations clearly
- [x] Keep messaging premium and clear

### 24. Paper Validation

- [x] Run end-to-end execution tests
- [ ] Run persistence tests (deferred — requires live DB; covered in SENTINEL gate)
- [ ] Run restart/redeploy tests (deferred — Fly.io env; covered in SENTINEL gate)
- [x] Store logs and evidence

### Done Condition

- [x] The bot is usable as a real paper trading product

---

## PRIORITY 4 — Wallet Lifecycle Foundation

Build this after the paper product is solid.

### 25. Wallet Domain Model

- [x] Finalize wallet entity model
- [x] Settle ownership model
- [x] Finalize wallet status/state model

### 26. Wallet Lifecycle

- [x] Build create/init wallet lifecycle
- [x] Build link/unlink lifecycle
- [x] Build activation/deactivation lifecycle
- [x] Handle invalid/blocked wallet states

### 27. Secure Wallet Persistence

- [x] Persist wallet records safely
- [x] Handle secrets safely
- [x] Add minimum audit trail

### 28. Wallet Auth Boundary

- [x] Verify ownership clearly
- [x] Separate admin vs user wallet access
- [x] Prevent privilege crossover

### 29. Wallet Surfaces

- [x] Show wallet status clearly
- [x] Show wallet lifecycle state clearly
- [ ] Show link state clearly (deferred — full link surface to Priority 6 multi-wallet lane)
- [x] Keep user-facing copy safe

### 30. Wallet Recovery and Tests

- [x] Handle broken-link recovery
- [x] Handle stale wallet recovery
- [x] Handle duplicate wallet conflicts
- [x] Add lifecycle tests
- [x] Add integration tests

### Done Condition

- [ ] Wallet lifecycle is complete and stable — pending SENTINEL MAJOR validation

---

## PRIORITY 5 — Portfolio Management Logic

Build this after wallet lifecycle is ready.

### 31. Portfolio Model

- [x] Refine portfolio entity model
- [x] Refine per-user portfolio model
- [x] Refine per-wallet portfolio relation

### 32. Exposure Aggregation

- [x] Build aggregate exposure logic
- [x] Build per-market exposure logic
- [x] Build per-user exposure logic
- [ ] Build per-wallet exposure logic (deferred to Priority 6 multi-wallet lane)

### 33. Allocation Logic

- [x] Build bankroll allocation model
- [x] Build strategy allocation model
- [x] Build user/wallet-aware allocation

### 34. PnL Logic

- [x] Build realized PnL computation
- [x] Build unrealized PnL computation
- [x] Build portfolio-level summary
- [x] Build history/snapshot structure

### 35. Portfolio Guardrails

- [x] Enforce exposure caps
- [x] Enforce drawdown caps
- [x] Enforce concentration caps
- [x] Connect portfolio logic to kill switch

### 36. Portfolio Surfaces and Validation

- [x] Show portfolio summary in bot/API
- [x] Show admin/operator portfolio surface
- [x] Add persistence and recovery
- [x] Validate all calculations (25/25 tests passing)
- [ ] Sync docs after completion (deferred to Priority 9 final docs lane)

### Done Condition

- [x] Portfolio is managed at system level, not manually

---

## PRIORITY 6 — Multi-Wallet Orchestration

Build this after wallet and portfolio are ready.

### 37. Orchestration Model

- [x] Define multi-wallet routing model
- [x] Define wallet selection rules
- [x] Define ownership-aware routing

### 38. Allocation Across Wallets

- [x] Build balance-aware allocation
- [x] Build strategy-aware allocation
- [x] Build risk-aware allocation
- [x] Build failover wallet selection

### 39. Cross-Wallet State Truth

- [x] Build unified view across wallets
- [x] Prevent duplicate/conflicting state
- [x] Build shared exposure truth

### 40. Cross-Wallet Controls

- [x] Add per-wallet enable/disable
- [x] Add per-wallet health status
- [x] Add per-wallet risk state
- [x] Add portfolio-wide control overlay

### 41. UX/API and Recovery

- [x] Add admin/operator visibility
- [x] Add safe user summaries if needed
- [x] Handle unavailable wallet cases
- [x] Handle routing conflicts
- [x] Handle degraded mode behavior

### 42. Persistence and Validation

- [x] Persist orchestration state
- [x] Persist reconciliation traces where needed
- [x] Add simulations/tests
- [ ] Sync docs after completion

### Done Condition

- [ ] The system can coordinate multiple wallets safely and truthfully (SENTINEL MAJOR validation pending before merge)

---

## PRIORITY 7 — Settlement, Retry, Reconciliation, and Ops Automation

Build this after orchestration is ready.

### 43. Settlement Workflow

- [x] Define settlement workflow
- [x] Define status transitions
- [x] Define idempotency model

### 44. Retry Engine

- [x] Define retry rules
- [x] Define retry caps
- [x] Define backoff strategy
- [x] Distinguish fatal vs retryable failures

### 45. Batching Logic

- [x] Define settlement batching rules
- [x] Define queueing model
- [x] Handle partial batches
- [x] Add batch observability

### 46. Reconciliation Logic

- [x] Build internal vs external reconciliation
- [x] Detect mismatches
- [x] Detect stuck states
- [x] Add repair/recovery flow

### 47. Operator Tooling

- [x] Show settlement status
- [x] Show retry status
- [x] Show failed batches
- [x] Add admin intervention paths

### 48. Persistence, Alerts, and Validation

- [x] Persist settlement events
- [x] Persist retry history
- [x] Persist reconciliation results
- [x] Add critical alerts
- [x] Add drift alerts
- [x] Validate all flows
- [x] DDL migration files created (Gate 1a — PR #786)
- [x] HTTP route wiring complete (Gate 1b — WARP/settlement-operator-routes)
- [x] Telegram wiring (Gate 1c — WARP/settlement-telegram-wiring)

### Done Condition

- [x] Ops flow is resilient, observable, and recoverable

---

## PRIORITY 8 — Production-Capital Readiness

This is the last major capability layer.

### 49. Capability Boundary Review

- [ ] Audit all paper-only assumptions
- [ ] Identify all unsafe areas for capital mode
- [ ] Define exact capital-readiness criteria

### 50. Capital-Mode Config Model

- [ ] Define capital-mode config
- [ ] Add strict feature gating
- [ ] Add explicit enable path
- [ ] Keep safeguards default-off

### 51. Capital Risk Controls Hardening

- [ ] Harden position sizing
- [ ] Harden max loss protection
- [ ] Harden drawdown protection
- [ ] Harden kill switch
- [ ] Harden circuit breakers

### 52. Live Execution Readiness

- [ ] Audit live execution path
- [ ] Verify live order flow truth
- [ ] Review external dependency risks
- [ ] Review failure modes
- [ ] Add rollback/disable path

### 53. Security and Observability Hardening

- [ ] Harden secret handling
- [ ] Harden permission model
- [ ] Harden admin action guardrails
- [ ] Add production-grade alerting
- [ ] Add incident visibility
- [ ] Prepare runbooks

### 54. Capital Validation and Claim Review

- [ ] Run dry-run validation
- [ ] Run staged rollout validation
- [ ] Review docs/policy/claims
- [ ] Remove overclaim
- [ ] Make release decision

### Done Condition

- [ ] The project can truthfully claim production-capital readiness

---

## PRIORITY 9 — Final Product Completion, Launch Assets, and Handoff

This is the final finish layer.

### 55. Public Product Assets

- [ ] Finalize README
- [ ] Finalize docs sync
- [ ] Finalize launch summary
- [ ] Finalize onboarding docs
- [ ] Finalize support/help docs

### 56. Ops Handoff Assets

- [ ] Prepare deployment guide
- [ ] Prepare secrets/env guide
- [x] Prepare troubleshooting guide
- [x] Prepare incident guide
- [x] Prepare rollback guide

### 57. Monitoring and Admin Surfaces

- [ ] Finalize project monitor
- [ ] Finalize admin visibility
- [ ] Finalize operator checklists
- [ ] Finalize release dashboard

### 58. Repo Hygiene Final

- [ ] Clean stale docs
- [ ] Clarify/archive stale reports
- [ ] Finalize roadmap sync
- [ ] Finalize project state sync
- [ ] Remove misleading checklists

### 59. Validation Archive

- [ ] Organize FORGE reports
- [ ] Organize SENTINEL reports
- [ ] Organize BRIEFER assets
- [ ] Preserve milestone evidence

### 60. Final Acceptance

- [ ] Confirm runtime stability
- [ ] Confirm persistence stability
- [ ] Confirm wallet lifecycle completion
- [ ] Confirm portfolio completion
- [ ] Confirm multi-wallet orchestration completion
- [ ] Confirm settlement/retry/reconciliation completion
- [ ] Confirm capital readiness completion
- [ ] Confirm docs and ops completion
- [ ] Get final COMMANDER acceptance

### Done Condition

- [ ] Project is finished 100%

---

### Simple Execution Order

- [x] PRIORITY 1 — Public Bot Runtime and Baseline
- [x] PRIORITY 2 — DB, Persistence, and Runtime Hardening
- [x] PRIORITY 3 — Paper Trading Product Completion
- [x] PRIORITY 4 — Wallet Lifecycle Foundation
- [x] PRIORITY 5 — Portfolio Management Logic
- [ ] PRIORITY 6 — Multi-Wallet Orchestration
- [ ] PRIORITY 7 — Settlement / Retry / Reconciliation
- [ ] PRIORITY 8 — Production-Capital Readiness
- [ ] PRIORITY 9 — Final Completion / Handoff / Launch Assets

---

### Right Now

- [x] COMMANDER to scope Priority 3 paper trading product completion
- [x] Define paper balance model (section 17 — first task)
- [x] Define paper order intent flow (section 18 — first task)
- [x] Priority 3 kickoff — paper account model + execution engine first
- [x] COMMANDER: review SENTINEL MAJOR validation for NWAP/paper-product-core before merge — PR #770 merged to main 2026-04-25 11:38 WIB
- [x] COMMANDER: scope Priority 4 wallet lifecycle foundation kickoff — confirmed 2026-04-25; branch NWAP/wallet-lifecycle-foundation
- [ ] SENTINEL: validate Priority 4 wallet lifecycle foundation — source projects/polymarket/polyquantbot/reports/forge/wallet-lifecycle-foundation.md; Tier: MAJOR
- [x] COMMANDER: scope Priority 6 multi-wallet orchestration Phase A kickoff — confirmed 2026-04-25; branch NWAP/multi-wallet-orchestration
- [ ] SENTINEL: validate Priority 6 Phase A orchestration foundation — source projects/polymarket/polyquantbot/reports/forge/multi-wallet-orchestration-phase-a.md; Tier: MAJOR
- [x] FORGE-X: Priority 6 Phase C (sections 41-42) built on NWAP/multi-wallet-orchestration-phase-c — 18/18 tests passing (WO-28..WO-45)
- [ ] SENTINEL: validate Priority 6 Phase C — source projects/polymarket/polyquantbot/reports/forge/multi-wallet-orchestration-phase-c.md; Tier: MAJOR
