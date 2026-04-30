# CrusaderBot — Launch Summary

**As of:** 2026-04-30
**Status:** Priority 8 build complete — paper-only boundary preserved — pending operator activation

---

## What Shipped

### Priority 8 — Capital Readiness (all merged to main)

| PR | Lane | SENTINEL | Notes |
|---|---|---|---|
| #790 | P8-A: BoundaryRegistry + CapitalModeConfig | APPROVED 98/100 | 16/16 tests |
| #794 | P8-B: CapitalRiskGate hardening | APPROVED 97/100 | 12/12 tests |
| #795 | P8-C: LiveExecutionGuard | CONDITIONAL 78/100 | FLAG-1 carried |
| #800 | P8-D: Security + observability hardening | APPROVED 97/100 | FLAG-1 fixed |
| #813 | Real CLOB execution path (NARROW INTEGRATION) | APPROVED 98/100 | 30/30 + 70/70 |
| #815 | Capital-mode-confirm DB layer + API scaffold | APPROVED 97/100 | chunk1 |
| #818 | Capital-mode-confirm live integration | APPROVED 100/100 | 167/167 tests |

### Earlier Priorities (all merged)

- Priority 3: Paper trading product — PaperEngine, PaperBetaWorker, Telegram portfolio surface
- Priority 4: Wallet lifecycle foundation — FSM, PostgreSQL store, lifecycle service
- Priority 5: Portfolio management — positions, PnL, exposure, guardrails, FastAPI routes
- Priority 6: Multi-wallet orchestration — WalletOrchestrator, CrossWalletStateAggregator, overlay controls
- Priority 7: Settlement engine — SettlementWorkflowEngine, RetryEngine, BatchProcessor, ReconciliationEngine, OperatorConsole
- Priority 2 (Deployment Hardening): SENTINEL APPROVED 98/100 — Fly.io deploy fully production-ready (PR #759)

---

## What is Live (Paper Only)

- FastAPI control plane: `/health`, `/ready`, `/beta/status`, `/beta/admin`
- Telegram operator shell with full command surface
- Paper trading worker spine (market sync, signal runner, risk monitor, position monitor)
- Multi-user backend: user, account, wallet ownership and session scope
- Portfolio PnL, exposure, guardrails
- Settlement engine with retry + reconciliation + operator controls
- Multi-wallet orchestration with overlay halt/enable/disable controls
- Two-layer capital-mode-confirm gate: env var + DB receipt (built and validated, NOT activated)
- Real CLOB execution adapter (built, guarded behind `EXECUTION_PATH_VALIDATED` — NOT active)

---

## What is Pending Activation

Three env guards must be explicitly set by the operator to move from paper to live:

1. `EXECUTION_PATH_VALIDATED` — set in deployment env after WARP🔹CMD + Mr. Walker review
2. `CAPITAL_MODE_CONFIRMED` — requires step 1 + operator `/capital_mode_confirm` two-step on Telegram (DB receipt persisted)
3. `ENABLE_LIVE_TRADING` — final execution authority gate

**None of these are currently set.** No live-trading or production-capital readiness is claimed.

For activation sequence, see `docs/ops/secrets_env_guide.md`.

---

## Priority 9 — Final Product Completion (in progress)

| Lane | Branch | Status |
|---|---|---|
| Lane 4 — Repo hygiene + archive sweep | `WARP/p9-repo-hygiene-final` | Merged (PR #821) |
| Lane 1 — Public product docs | `WARP/p9-public-product-docs` | In Progress |
| Lane 2 — Ops handoff | `WARP/p9-ops-handoff` | In Progress |
| Lane 3 — Admin/monitoring surfaces | `WARP/p9-monitoring-admin-surfaces` | Not Started |
| Lane 5 — Final acceptance | `WARP/p9-final-acceptance` | Not Started (gated) |
