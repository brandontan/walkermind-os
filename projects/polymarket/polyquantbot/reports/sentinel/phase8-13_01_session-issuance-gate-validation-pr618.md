Environment
- Date (Asia/Jakarta): 2026-04-19 23:33
- Validation role: SENTINEL
- Validation tier: MAJOR
- Target PR: #618
- Target branch (declared): claude/fix-telegram-session-issuance-zGD86
- Working branch observed by git: work (Codex detached/worktree normalization)

Validation Context
- Objective: re-validate the blocked contract from PR #616 and confirm PR #618 enforces strict active-only session issuance.
- Required checks:
  1) auto-promotion fully removed
  2) pending_confirmation -> rejected
  3) no activation-state mutation side effect during issuance
  4) active user still receives session issuance
  5) tenant isolation preserved
  6) runtime/client reply mapping matches backend behavior
  7) claimed 148/148 pytest evidence truthful OR conditionally gated when non-reproducible

Phase 0 Checks
- Forge report present: PASS (`projects/polymarket/polyquantbot/reports/forge/phase8-13_02_fix-session-issuance-gate.md`).
- PROJECT_STATE.md present with full timestamp format: PASS.
- py_compile rerun by SENTINEL on key touched files: PASS.
- pytest reproducibility on this runner: FAIL (dependency/environment gate; `pydantic` missing in Python 3.10 runner).

Findings
1) Auto-promotion removed: PASS
- `TelegramSessionIssuanceService.issue()` rejects any non-active activation status and contains no activation mutation call.
- No `set_activation_status` invocation exists in issuance service.

2) pending_confirmation returns rejected: PASS
- Service gate: `if settings.activation_status != "active": return rejected`.
- Unit/integration test coverage explicitly asserts pending -> rejected.

3) No activation-state mutation side effect in issuance: PASS
- Issuance service only reads user/settings and calls `AuthSessionService.issue_session()` for active users.
- Activation mutation remains in `TelegramActivationService.confirm()` via `set_activation_status(..., "active")`.

4) Active users still receive session issuance: PASS
- Service returns `session_issued` with a session_id for active users.
- Tests cover active issuance and repeated active issuance.

5) Tenant isolation preserved: PASS
- Service lookup is tenant-scoped (`get_user_by_external_id(tenant_id=..., external_id=...)`).
- Dedicated test verifies same telegram_user_id across t1/t2 remains isolated.

6) Runtime/client reply mapping truthful: PASS
- Backend client maps `/auth/telegram-onboarding/session-issue` response outcome to typed `TelegramSessionIssuanceResult`.
- Runtime maps:
  - `session_issued` -> success reply
  - `already_active_session_issued` -> welcome-back reply
  - `rejected` -> activation rejected reply
  - other/error -> identity error reply
- Mapping remains aligned with backend contract for rejected/issued/error outcomes.

7) Claimed 148/148 pytest evidence: CONDITIONAL
- Could not fully reproduce in this runner because required runtime deps are missing (`ModuleNotFoundError: pydantic`) when collecting tests.
- Claim is conditionally accepted pending dependency-complete rerun evidence in COMMANDER/CI environment.

Score Breakdown
- Contract correctness: 35/35
- Safety/no hidden mutation: 25/25
- Tenant isolation: 10/10
- Runtime/client mapping truthfulness: 15/15
- Reproducible test evidence in current runner: 0/15 (environment-gated)
- Report/traceability completeness: 10/10
- Total: 95/100

Critical Issues
- None in code-path contract checks.
- One gate item remains: local reproducibility of 148/148 pytest claim on dependency-complete environment.

Status
- Verdict: CONDITIONAL

PR Gate Result
- PR #618 may proceed only with conditional gate: COMMANDER must require one reproducible dependency-complete pytest rerun (or CI artifact) for the claimed 148/148 before final merge decision.

Broader Audit Finding
- The blocked behavior from PR #616 (issuance-time auto-promotion) is not present in the current issuance service implementation.
- Activation authority is correctly centralized in `TelegramActivationService.confirm()`.

Reasoning
- Core safety contract (active-only issuance with no silent activation mutation) is implemented and test-targeted.
- Only unresolved item is environment reproducibility of total-suite count claim on this runner.

Fix Recommendations
- Run and attach dependency-complete evidence for:
  - `PYTHONPATH=. pytest -q projects/polymarket/polyquantbot/tests`
- Ensure environment includes at minimum: `pydantic`, `fastapi`, and test stack versions used in forge evidence.

Out-of-scope Advisory
- `already_active_session_issued` remains mapped in runtime/client contract while service currently always returns `session_issued` for active path; distinction can be added later without affecting this gate.

Deferred Minor Backlog
- [DEFERRED] Resolve pytest warning: `Unknown config option: asyncio_mode` in environment where pytest plugin/config alignment is expected.

Telegram Visual Preview
- PASS summary:
  - active-only issuance enforced
  - pending_confirmation rejected
  - no issuance-side activation mutation
  - tenant isolation preserved
  - runtime reply mapping aligned
- CONDITIONAL gate:
  - 148/148 claim not reproducible on this runner due to missing dependencies
