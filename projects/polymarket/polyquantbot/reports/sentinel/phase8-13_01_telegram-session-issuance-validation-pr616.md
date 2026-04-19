# SENTINEL Validation Report — PR #616

## Environment
- Timestamp (Asia/Jakarta): 2026-04-19 22:47
- Validator role: SENTINEL
- Validation tier: MAJOR
- Target PR: #616
- Target branch: feature/task-title-2026-04-19-d9ai2m
- Repository execution branch context: `work` (Codex detached/worktree normalization)

## Validation Context
- Blueprint source reviewed: `docs/crusader_multi_user_architecture_blueprint.md`
- Declared claim levels:
  - Phase 8.12 closeout: REPO TRUTH SYNC ONLY
  - Phase 8.13 implementation: FOUNDATION
- Primary validation target:
  - Telegram session-issuance handoff foundation only
  - Outcome contract correctness (`session_issued`, `already_active_session_issued`, `rejected`, `error`)
  - Activated/already-active gating, tenant isolation, runtime mapping continuity

## Phase 0 Checks
- Forge report exists and naming is valid:
  - `projects/polymarket/polyquantbot/reports/forge/phase8-13_01_telegram-session-issuance-handoff-foundation.md`
- Forge report has required MAJOR sections: PASS
- PROJECT_STATE timestamp format check: PASS (`YYYY-MM-DD HH:MM`)
- Roadmap/state consistency for active lane (8.13 in progress, awaiting SENTINEL): PASS
- `python3 -m py_compile` on touched implementation/test files: PASS
- `pytest -q projects/polymarket/polyquantbot/tests/test_phase8_13_telegram_session_issuance_20260419.py`: NOT REPRODUCED (environment dependency gap: `pydantic` missing)
- Mojibake scan (UTF-8 corruption signatures) on scoped files: PASS (no matches)

## Findings

### Critical-1 — Session issuance service violates activated/already_active gate
- Severity: CRITICAL
- Expected:
  - Session issuance should be reachable only when user is already in activated/already_active state.
  - Non-active state should return `rejected` (or equivalent blocked path), not auto-promote to active.
- Actual:
  - `TelegramSessionIssuanceService.issue(...)` auto-updates non-active users to `active` and then issues session, returning `session_issued`.
  - This allows a `pending_confirmation` user to obtain a session directly via `/auth/telegram-onboarding/session-issue` without prior confirmed active state gate.
- Evidence:
  - Service auto-promote path in `server/services/telegram_session_issuance_service.py`.
  - Integration tests assert this behavior as allowed (`pending -> session_issued`) in `tests/test_phase8_13_telegram_session_issuance_20260419.py`.
- Impact:
  - Claim drift versus requested validation target for strict activation-gated issuance.
  - Route-level contract currently permits bypass of explicit activation gate semantics.

### Major-2 — Runtime vs backend contract semantic inconsistency on activation boundary
- Severity: MAJOR
- Expected:
  - Activation and issuance semantics should be coherent across runtime and backend route.
- Actual:
  - Runtime path with `activation_confirmer` returns `_REPLY_ACTIVATED` and exits on `activated`, while backend issuance service independently permits pending->active->session issuance.
  - Net effect: same lifecycle state can yield different behavior depending on which boundary is called first.
- Evidence:
  - Runtime early-return on activation outcome `activated` in `client/telegram/runtime.py`.
  - Backend service auto-activation+issue in `server/services/telegram_session_issuance_service.py`.

### Informational-1 — Scope claims mostly truthful for FOUNDATION lane
- Exclusion claims (no OAuth/RBAC/delegated signing/exchange rollout/portfolio rollout/full polished UX) are not contradicted by code in scoped files.
- Tenant lookup remains tenant-scoped via `get_user_by_external_id(tenant_id, external_id)` and `AuthSessionService.issue_session(...)` user-tenant enforcement.

## Score Breakdown
- Contract correctness (issuance outcomes + gate semantics): 17/30
- Route/runtime integration coherence: 17/25
- Tenant isolation / ownership integrity: 20/20
- Tests and evidence quality: 10/15
- Docs/state/roadmap alignment: 8/10
- **Total: 72/100**

## Critical Issues
1. Activated/already-active gate violation in session issuance service (`pending_confirmation` can receive session issuance through auto-promotion).

## Status
- **BLOCKED**

## PR Gate Result
- **Do not merge PR #616 in current state.**

## Broader Audit Finding
- This lane remains FOUNDATION-scoped, but the present issuance gate weakens lifecycle integrity by allowing activation transition inside the issuance boundary itself.

## Reasoning
- MAJOR lane requested strict validation of activation-gated issuance. Current implementation materially contradicts that gate requirement.
- Tenant isolation and ownership checks are present, but lifecycle gate semantics are core to claimed behavior and must be fixed before approval.

## Fix Recommendations
1. In `TelegramSessionIssuanceService.issue(...)`, require `activation_status == "active"` before issuing session.
2. For `activation_status != "active"`, return deterministic `rejected` with explicit detail (e.g., `activation_required`).
3. Update Phase 8.13 tests to assert rejection for pending_confirmation path and preserve allowed active/already_active session issuance paths.
4. Keep runtime reply mapping coherent with the corrected contract and re-run targeted + dependent regression tests in dependency-complete environment.

## Out-of-scope Advisory
- No additional command-surface expansion reviewed beyond `/start` and current auth/onboarding/activation/session-handoff surfaces.

## Deferred Minor Backlog
- [DEFERRED] Pytest warning `Unknown config option: asyncio_mode` persists as non-blocking hygiene issue.

## Telegram Visual Preview
- `session_issued` -> "Welcome to CrusaderBot. Your session is ready."
- `already_active_session_issued` -> "Welcome back. Your account is already active and your session is ready."
- `rejected` -> currently mapped to activation-rejected reply
- `error` -> currently mapped to identity/backend error reply
