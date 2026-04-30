## CrusaderBot Work Checklist

Last Updated: 2026-05-01 02:55 Asia/Jakarta

---

## Current Truth

CrusaderBot is at the public paper-beta finish layer.

Priority 1 through Priority 7 are complete.
Priority 8 production-capital readiness build is complete, but activation remains gated.
Priority 9 final product completion is nearly complete:
- Lane 4 repo hygiene final: DONE via PR #822.
- Lane 1+2 public product docs + ops handoff: DONE via PR #825, PR #826, PR #827.
- Lane 3 monitoring/admin surfaces: DONE via PR #831.
- Lane 5 final acceptance: OPEN / gated.

Activation guards remain off:
- `EXECUTION_PATH_VALIDATED` NOT SET
- `CAPITAL_MODE_CONFIRMED` NOT SET
- `ENABLE_LIVE_TRADING` NOT SET

No live-trading or production-capital readiness claim is authorized.

---

## PRIORITY 8 — Production-Capital Readiness

Status: BUILD COMPLETE / ACTIVATION GATED

- [x] P8-A capability boundary review
- [x] P8-B capital risk controls hardening
- [x] P8-C live execution readiness
- [x] P8-D security and observability hardening
- [x] P8-E capital validation and claim review
- [x] Real CLOB execution-path foundation merged via PR #813
- [x] Capital-mode-confirm DB gate merged via PR #815 and PR #818
- [ ] Make release/activation decision
  - Deferred: `EXECUTION_PATH_VALIDATED` and `CAPITAL_MODE_CONFIRMED` env vars are NOT SET.
  - Deferred: operator `/capital_mode_confirm` DB receipt is required before capital activation.
- [ ] Claim production-capital readiness
  - Blocked until owner + WARP🔹CMD activation decision and evidence.

---

## PRIORITY 9 — Final Product Completion, Launch Assets, and Handoff

Status: FINAL ACCEPTANCE PREP

### 55. Public Product Assets

- [x] Finalize README
- [x] Finalize docs sync
- [x] Finalize launch summary
- [x] Finalize onboarding docs
- [x] Finalize support/help docs

Completed via Priority 9 Lane 1+2:
- PR #825
- PR #826
- PR #827
- Branch: `WARP/p9-readiness-docs-ops`

### 56. Ops Handoff Assets

- [x] Prepare deployment guide
- [x] Prepare secrets/env guide
- [x] Prepare troubleshooting guide
- [x] Prepare incident guide
- [x] Prepare rollback guide
- [x] Prepare runbook quick reference

Completed via Priority 9 Lane 1+2:
- PR #825
- PR #826
- PR #827
- Branch: `WARP/p9-readiness-docs-ops`

### 57. Monitoring and Admin Surfaces

- [x] Finalize project monitor
- [x] Finalize admin visibility
- [x] Finalize operator checklist
- [x] Finalize release dashboard

Completed via Priority 9 Lane 3:
- PR #831
- Branch: `WARP/p9-monitoring-admin-surfaces`
- Files:
  - `docs/ops/monitoring_admin_index.md`
  - `docs/ops/operator_checklist.md`
  - `docs/release_dashboard.md`
  - `reports/forge/p9-monitoring-admin-surfaces.md`

### 58. Repo Hygiene Final

- [x] Clean stale docs
- [x] Clarify/archive stale reports
- [x] Finalize roadmap sync
- [x] Finalize project state sync
- [x] Remove misleading checklists

Completed via Priority 9 Lane 4:
- PR #822
- Branch: `WARP/p9-repo-hygiene-final`

### 59. Validation Archive

- [x] Organize FORGE reports
- [x] Organize SENTINEL reports
- [x] Preserve milestone evidence
- [ ] Organize BRIEFER assets
  - Deferred unless final public handoff requires a new BRIEFER artifact.

### 60. Final Acceptance

- [ ] Confirm runtime stability
  - Requires live smoke evidence before public announcement.
- [ ] Confirm persistence stability
  - Requires DB/persistence evidence where applicable.
- [x] Confirm wallet lifecycle completion
- [x] Confirm portfolio completion
- [x] Confirm multi-wallet orchestration completion
- [x] Confirm settlement/retry/reconciliation completion
- [ ] Confirm capital readiness completion
  - Build complete, activation gated; production-capital claim remains blocked.
- [x] Confirm docs and ops completion
  - Lane 1+2 + Lane 3 + Lane 4 merged.
- [ ] Get final COMMANDER acceptance
  - Current branch prepares this gate.

Done condition:
- [ ] Project is finished 100% as public paper-beta, with activation boundaries explicit.
- [ ] Any live/capital activation decision is recorded as a separate Mr. Walker + WARP🔹CMD gate.

---

## Simple Execution Order

- [x] PRIORITY 1 — Public Bot Runtime and Baseline
- [x] PRIORITY 2 — DB, Persistence, and Runtime Hardening
- [x] PRIORITY 3 — Paper Trading Product Completion
- [x] PRIORITY 4 — Wallet Lifecycle Foundation
- [x] PRIORITY 5 — Portfolio Management Logic
- [x] PRIORITY 6 — Multi-Wallet Orchestration
- [x] PRIORITY 7 — Settlement / Retry / Reconciliation
- [ ] PRIORITY 8 — Production-Capital Readiness
  - Build complete; activation gated.
- [ ] PRIORITY 9 — Final Completion / Handoff / Launch Assets
  - Lanes 1+2, 3, and 4 complete; Lane 5 final acceptance open.

---

## Right Now

- [x] Merge Priority 9 Lane 3 monitoring/admin surfaces — PR #831.
- [x] Start combined post-merge state sync + final acceptance prep.
- [ ] Merge `WARP/p9-post-merge-final-acceptance`.
- [ ] Run final acceptance decision.
- [ ] Decide activation posture:
  - Public paper-beta final acceptance only, or
  - Separate owner-gated capital/live activation sequence.
