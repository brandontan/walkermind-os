## CrusaderBot Work Checklist

### From Now to Finish

---

PRIORITY 1 — Bot Public-Ready Baseline

This must be finished first.

Status Snapshot (2026-04-21)

DONE / Mostly Done

[x] Fly app is alive

[x] Telegram runtime is active on Fly

[x] Telegram startup is automatic in the deploy path

[x] /ready includes Telegram runtime truth

[x] /start replies on deployed environment

[x] Onboarding/public-safe/paper-only copy refined

[x] Fallback/error copy refined


ACTIVE (Current lane)

Ops Handoff / Troubleshooting Lane

[x] Publish operator runbook for current runtime posture and public-safe paper-only claims

[x] Publish Fly runtime troubleshooting quick guide

[x] Publish Telegram runtime troubleshooting quick guide

[x] Publish Sentry quick-check note (integration present vs first-event proof pending)

[x] Publish reusable runtime evidence capture checklist


[x] Fix /help command semantics so it reaches real help handler (no /start collapse)

[x] Fix /status command semantics so it reaches real status handler (no /start collapse)

[x] Ensure command routing precedence no longer collapses non-/start commands into /start lifecycle/session path

[x] Integrate Telegram design/presentation layer into live `/start`, `/help`, `/status` reply builders (repo code truth)

[x] Consolidate remaining public-safe replies (onboarding required, already-linked/activated/session-ready variants, unknown command, temporary identity/runtime/backend errors) to shared presentation helpers

[x] Align `/help` to trusted public-safe command surface only (hide operator-managed or not-ready commands from public guide)


NEXT (immediately after code fix + UX integration)

[ ] Redeploy latest command-routing + Telegram UX integration to Fly

[ ] Verify live Telegram behavior for /start, /help, and /status

[ ] Save fresh deploy evidence (logs + /health + /ready + command replies, including improved Telegram reply formatting)


2. Baseline Public Commands

[ ] Make sure responses are not empty or dummy

[ ] Make sure there is no timeout or silent failure


3. Path to Public Telegram UX Refinement

[ ] Refine the existing Telegram onboarding flow

[ ] Refine the existing Telegram command UX

[ ] Refine the current welcome intro for new users

[ ] Refine the current help and status copy

[ ] Refine paper-only messaging across the existing Telegram flow

[ ] Refine the next-step guidance for new users

[ ] Refine the unlinked-user flow using the current foundation

[ ] Refine the linked-user flow using the current foundation

[ ] Refine fallback and error messaging

[ ] Refine Telegram formatting and readability


4. Public Command Set

[x] Keep the existing public command baseline clean and useful

[ ] Prepare /paper

[ ] Prepare /about

[ ] Prepare /risk

[ ] Prepare /account or /link

[x] Separate public commands from admin/operator commands

[x] Hide commands that are not ready yet


5. Public-Safe Boundaries

[ ] Do not claim live trading readiness

[ ] Do not claim production-capital readiness

[ ] Keep the paper-only boundary visible everywhere

[ ] Guard admin/internal paths properly


6. Observability Baseline

[ ] Add bot startup logs

[ ] Add command received logs

[ ] Add command handled logs

[ ] Add reply success/failure logs

[ ] Add missing env / disabled mode logs

[x] Add Sentry Python runtime initialization + exception capture guardrails (env-only `SENTRY_DSN`, FastAPI + Telegram/runtime exception surfaces)


7. End-to-End Validation

[ ] Deploy the latest version

[ ] Confirm /health is OK

[ ] Confirm /ready is OK

[ ] Confirm /start is OK

[ ] Confirm /help is OK

[ ] Confirm /status is OK

[ ] Save validation evidence


Done Condition

[ ] The bot is truly usable as a public-ready paper bot baseline


---

PRIORITY 2 — DB, Persistence, and Runtime Hardening

Finish this after the public bot baseline works.

9. Supabase / Postgres Integration Hardening

[ ] Finalize a stable DATABASE_URL

[ ] Make sure sslmode=require is used where needed

[ ] Confirm pooled connection strategy

[ ] Add DB health checks

[ ] Make sure startup does not fail when DB is slow


10. Persistence Stabilization

[ ] Audit any state still stored in files or temp storage

[ ] Move critical user/session state into DB

[ ] Move link/account state into DB

[ ] Remove split-brain state between file storage and DB

[ ] Make sure restart/redeploy does not break state


11. Runtime Config Hardening

[ ] Validate required env vars at boot

[ ] Make missing-secret errors clear

[ ] Reduce unsafe defaults

[ ] Make startup config summary safe and truthful


12. Health / Readiness Truth Hardening

[ ] Make /health check the main process properly

[ ] Make /ready check relevant dependencies properly

[ ] Include Telegram runtime state in readiness

[ ] Include DB state in readiness

[ ] Remove false green status


13. Error Handling and Resilience

[ ] Make graceful shutdown work properly

[ ] Make restart safety reliable

[ ] Prevent worker crash from corrupting state

[ ] Add retry handling for non-fatal dependencies

14. Logging and Monitoring Hardening

[ ] Keep structured logging consistent

[ ] Improve startup logs

[ ] Make error traces easy to follow

[ ] Prepare minimum viable monitoring


15. Security Baseline

[ ] Make sure secrets never appear in logs

[ ] Remove any hardcoded credentials

[ ] Protect admin access properly

[ ] Restrict sensitive routes


16. Deployment Hardening

[ ] Clean up the Dockerfile

[ ] Keep fly.toml in sync

[ ] Define restart policy clearly

[ ] Define rollback strategy clearly

[ ] Define post-deploy smoke tests clearly


Done Condition

[ ] The bot is not just running, but stable and persistent


---

PRIORITY 3 — Paper Trading Product Completion

Finish this after runtime and persistence are stable.

17. Paper Account Model

[ ] Define the paper balance model

[ ] Define paper position tracking

[ ] Define paper PnL tracking

[ ] Add reset/test flow for operators


18. Paper Execution Engine

[ ] Define paper order intent flow

[ ] Enable paper entry logic

[ ] Enable paper exit logic

[ ] Make paper fill assumptions clear

[ ] Make paper execution logging clear

19. Paper Portfolio Surface

[ ] Show open paper positions

[ ] Show realized PnL

[ ] Show unrealized PnL

[ ] Show summary through bot/API


20. Paper Risk Controls

[ ] Enforce exposure caps

[ ] Enforce drawdown caps

[ ] Enforce kill switch

[ ] Show risk state clearly


21. Paper Strategy Visibility

[ ] Show strategy state

[ ] Show signal state

[ ] Show enable/disable visibility

[ ] Show suppressed/blocked reasons

22. Admin / Operator Paper Controls

[ ] Show runtime paper summary

[ ] Show readiness paper state

[ ] Add pause/resume if supported

[ ] Keep admin commands separate


23. Public Paper UX Completion

[ ] Make sure users understand paper mode

[ ] Show paper product status clearly

[ ] Show product limitations clearly

[ ] Keep messaging premium and clear


24. Paper Validation

[ ] Run end-to-end execution tests

[ ] Run persistence tests

[ ] Run restart/redeploy tests

[ ] Store logs and evidence


Done Condition

[ ] The bot is usable as a real paper trading product


---

PRIORITY 4 — Wallet Lifecycle Foundation

Build this after the paper product is solid.

25. Wallet Domain Model

[ ] Finalize wallet entity model

[ ] Settle ownership model

[ ] Finalize wallet status/state model


26. Wallet Lifecycle

[ ] Build create/init wallet lifecycle

[ ] Build link/unlink lifecycle

[ ] Build activation/deactivation lifecycle

[ ] Handle invalid/blocked wallet states


27. Secure Wallet Persistence

[ ] Persist wallet records safely

[ ] Handle secrets safely

[ ] Add minimum audit trail


28. Wallet Auth Boundary

[ ] Verify ownership clearly

[ ] Separate admin vs user wallet access

[ ] Prevent privilege crossover


29. Wallet Surfaces

[ ] Show wallet status clearly

[ ] Show wallet lifecycle state clearly

[ ] Show link state clearly

[ ] Keep user-facing copy safe


30. Wallet Recovery and Tests

[ ] Handle broken-link recovery

[ ] Handle stale wallet recovery

[ ] Handle duplicate wallet conflicts

[ ] Add lifecycle tests

[ ] Add integration tests


Done Condition

[ ] Wallet lifecycle is complete and stable


---

PRIORITY 5 — Portfolio Management Logic

Build this after wallet lifecycle is ready.

31. Portfolio Model

[ ] Refine portfolio entity model

[ ] Refine per-user portfolio model

[ ] Refine per-wallet portfolio relation


32. Exposure Aggregation

[ ] Build aggregate exposure logic

[ ] Build per-market exposure logic

[ ] Buill per-user exposure logic

[ ] Build per-wallet exposure logic


33. Allocation Logic

[ ] Build bankroll allocation model

[ ] Build strategy allocation model

[ ] Build user/wallet-aware allocation


34. PnL Logic

[ ] Build realized PnL computation

[ ] Build unrealized PnL computation

[ ] Build portfolio-level summary

[ ] Build history/snapshot structure


35. Portfolio Guardrails

[ ] Enforce exposure caps

[ ] Enforce drawdown caps

[ ] Enforce concentration caps

[ ] Connect portfolio logic to kill switch


36. Portfolio Surfaces and Validation

[ ] Show portfolio summary in bot/API

[ ] Show admin/operator portfolio surface

[ ] Add persistence and recovery

[ ] Validate all calculations

[ ] Sync docs after completion


Done Condition

[ ] Portfolio is managed at system level, not manually


---

PRIORITY 6 — Multi-Wallet Orchestration

Build this after wallet and portfolio are ready.

37. Orchestration Model

[ ] Define multi-wallet routing model

[ ] Define wallet selection rules

[ ] Define ownership-aware routing


38. Allocation Across Wallets

[ ] Build balance-aware allocation

[ ] Build strategy-aware allocation

[ ] Build risk-aware allocation

[ ] Build failover wallet selection


39. Cross-Wallet State Truth

[ ] Build unified view across wallets

[ ] Prevent duplicate/conflicting state

[ ] Build shared exposure truth


40. Cross-Wallet Controls

[ ] Add per-wallet enable/disable

[ ] Add per-wallet health status

[ ] Add per-wallet risk state

[ ] Add portfolio-wide control overlay


41. UX/API and Recovery

[ ] Add admin/operator visibility

[ ] Add safe user summaries if needed

[ ] Handle unavailable wallet cases

[ ] Handle routing conflicts

[ ] Handle degraded mode behavior


42. Persistence and Validation

[ ] Persist orchestration state

[ ] Persist reconciliation traces where needed

[ ] Add simulations/tests

[ ] Sync docs after completion


Done Condition

[ ] The system can coordinate multiple wallets safely and truthfully


---

PRIORITY 7 — Settlement, Retry, Reconciliation, and Ops Automation

Build this after orchestration is ready.

43. Settlement Workflow

[ ] Define settlement workflow

[ ] Define status transitions

[ ] Define idempotency model


44. Retry Engine

[ ] Define retry rules

[ ] Define retry caps

[ ] Define backoff strategy

[ ] Distinguish fatal vs retryable failures


45. Batching Logic

[ ] Define settlement batching rules

[ ] Define queueing model

[ ] Handle partial batches

[ ] Add batch observability


46. Reconciliation Logic

[ ] Build internal vs external reconciliation

[ ] Detect mismatches

[ ] Detect stuck states

[ ] Add repair/recovery flow


47. Operator Tooling

[ ] Show settlement status

[ ] Show retry status

[ ] Show failed batches

[ ] Add admin intervention paths


48. Persistence, Alerts, and Validation

[ ] Persist settlement events

[ ] Persist retry history

[ ] Persist reconciliation results

[ ] Add critical alerts

[ ] Add drift alerts

[ ] Validate all flows

[ ] Sync docs after completion


Done Condition

[ ] Ops flow is resilient, observable, and recoverable


---

PRIORITY 8 — Production-Capital Readiness

This is the last major capability layer.

49. Capability Boundary Review

[ ] Audit all paper-only assumptions

[ ] Identify all unsafe areas for capital mode

[ ] Define exact capital-readiness criteria


50. Capital-Mode Config Model

[ ] Define capital-mode config

[ ] Add strict feature gating

[ ] Add explicit enable path

[ ] Keep safeguards default-off


51. Capital Risk Controls Hardening

[ ] Harden position sizing

[ ] Harden max loss protection

[ ] Harden drawdown protection

[ ] Harden kill switch

[ ] Harden circuit breakers


52. Live Execution Readiness

[ ] Audit live execution path

[ ] Verify live order flow truth

[ ] Review external dependency risks

[ ] Review failure modes

[ ] Add rollback/disable path


53. Security and Observability Hardening

[ ] Harden secret handling

[ ] Harden permission model

[ ] Harden admin action guardrails

[ ] Add production-grade alerting

[ ] Add incident visibility

[ ] Prepare runbooks


54. Capital Validation and Claim Review

[ ] Run dry-run validation

[ ] Run staged rollout validation

[ ] Review docs/policy/claims

[ ] Remove overclaim

[ ] Make release decision


Done Condition

[ ] The project can truthfully claim production-capital readiness


---

PRIORITY 9 — Final Product Completion, Launch Assets, and Handoff

This is the final finish layer.

55. Public Product Assets

[ ] Finalize README

[ ] Finalize docs sync

[ ] Finalize launch summary

[ ] Finalize onboarding docs

[ ] Finalize support/help docs


56. Ops Handoff Assets

[ ] Prepare deployment guide

[ ] Prepare secrets/env guide

[x] Prepare troubleshooting guide

[x] Prepare incident guide

[x] Prepare rollback guide


57. Monitoring and Admin Surfaces

[ ] Finalize project monitor

[ ] Finalize admin visibility

[ ] Finalize operator checklists

[ ] Finalize release dashboard


58. Repo Hygiene Final

[ ] Clean stale docs

[ ] Clarify/archive stale reports

[ ] Finalize roadmap sync

[ ] Finalize project state sync

[ ] Remove misleading checklists


59. Validation Archive

[ ] Organize FORGE reports

[ ] Organize SENTINEL reports

[ ] Organize BRIEFER assets

[ ] Preserve milestone evidence


60. Final Acceptance

[ ] Confirm runtime stability

[ ] Confirm persistence stability

[ ] Confirm wallet lifecycle completion

[ ] Confirm portfolio completion

[ ] Confirm multi-wallet orchestration completion

[ ] Confirm settlement/retry/reconciliation completion

[ ] Confirm capital readiness completion

[ ] Confirm docs and ops completion

[ ] Get final COMMANDER acceptance


Done Condition

[ ] Project is finished 100%


---

Simple Execution Order

[ ] PRIORITY 1 — Public Bot Runtime and Baseline

[ ] PRIORITY 2 — DB, Persistence, and Runtime Hardening

[ ] PRIORITY 3 — Paper Trading Product Completion

[ ] PRIORITY 4 — Wallet Lifecycle Foundation

[ ] PRIORITY 5 — Portfolio Management Logic

[ ] PRIORITY 6 — Multi-Wallet Orchestration

[ ] PRIORITY 7 — Settlement / Retry / Reconciliation

[ ] PRIORITY 8 — Production-Capital Readiness

[ ] PRIORITY 9 — Final Completion / Handoff / Launch Assets


---

Right Now

[ ] Redeploy/restart Fly with the latest secrets

[ ] Check Telegram startup logs

[ ] Make Telegram runtime truly active

[ ] Test /start

[ ] Test /help

[ ] Test /status
