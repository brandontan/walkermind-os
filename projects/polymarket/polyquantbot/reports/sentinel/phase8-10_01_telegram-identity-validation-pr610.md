# SENTINEL Validation Report — PR #610 (Phase 8.9 Closeout + Phase 8.10 Telegram Identity Resolution Foundation)

## Environment
- Date (Asia/Jakarta): 2026-04-19 16:09
- Validator role: SENTINEL
- Source PR: #610
- Source branch: claude/phase8-10-telegram-identity-ePWJP
- Project root: projects/polymarket/polyquantbot
- Validation Tier: MAJOR
- Claim levels reviewed:
  - Phase 8.9 closeout: REPO TRUTH SYNC ONLY
  - Phase 8.10 implementation: FOUNDATION

## Validation Context
Blueprint reviewed:
- docs/crusader_multi_user_architecture_blueprint.md

Primary scope validated:
1. Identity-resolution truth and scope boundaries
2. Backend lookup boundary (`get_user_by_external_id`) and tenant isolation
3. TelegramIdentityService contract (`resolved` / `not_found` / `error`)
4. Backend route integrity (`GET /auth/telegram-identity/{telegram_user_id}`)
5. Client/runtime integration (`CrusaderBackendClient`, `TelegramIdentityResolver`, `TelegramPollingLoop`)
6. Tests/docs/report/state alignment

## Phase 0 Checks
- Forge report exists and naming is valid:
  - projects/polymarket/polyquantbot/reports/forge/phase8-10_01_telegram-identity-resolution-foundation.md
- PROJECT_STATE.md present with full timestamp format.
- ROADMAP.md updated with Phase 8.9 closeout + Phase 8.10 checklist.
- Mojibake quick scan on inspected files: no corruption signatures found.
- Pre-flight command evidence gathered:
  - `locale` => `C.UTF-8` / `LC_ALL=C.UTF-8`
  - `python3 -m py_compile ...` => pass (targeted files)
  - `pytest -q ...` (8-file regression set) => environment-limited failure due missing dependencies (`fastapi`, unresolved `projects` import path in current runner)

## Findings
1. **Identity foundation scope claims are truthful (PASS).**
   - No code path introduces OAuth, RBAC, delegated signing lifecycle, exchange execution rollout, portfolio engine rollout, or production cross-client orchestration in this PR slice.
   - Runtime remains command-limited (`/start` + unknown fallback), consistent with foundation claim.

2. **Backend lookup boundary and tenant isolation are correct (PASS).**
   - `MultiUserStore`, `PersistentMultiUserStore`, and `InMemoryMultiUserStore` all implement tenant-scoped `get_user_by_external_id(tenant_id, external_id)` logic.
   - `UserService.get_user_by_external_id` is a thin boundary delegation with no ownership widening.

3. **TelegramIdentityService contract is coherent for expected paths (PASS).**
   - `resolve()` enforces empty-input error behavior, maps `external_id = "tg_{telegram_user_id}"`, handles store exceptions as `error`, and cleanly distinguishes `resolved` vs `not_found`.

4. **Backend identity route contract is minimal and pre-auth by design (PASS).**
   - `GET /auth/telegram-identity/{telegram_user_id}` is sessionless and returns only outcome + scope fields.
   - Route does not issue sessions and does not invoke handoff/session issuance logic.

5. **Client/runtime integration behavior is largely correct (PASS with one contract gap).**
   - `CrusaderBackendClient.resolve_telegram_identity()` correctly maps HTTP failures/exceptions to `error`.
   - `TelegramIdentityResolver` protocol is real and used by polling loop.
   - `TelegramPollingLoop` behavior matches intended matrix:
     - resolved -> dispatch with backend tenant/user
     - not_found -> unregistered reply, no dispatch
     - error -> identity-error reply, no dispatch
     - resolver exception -> identity-error reply, no dispatch
     - no resolver -> staging fallback preserved
     - non-command text -> resolution not triggered

6. **Contract hardening gap: unknown outcome is not normalized (NEEDS FIX).**
   - `CrusaderBackendClient.resolve_telegram_identity()` accepts arbitrary `outcome` strings from JSON and returns them through typed field without runtime normalization.
   - `TelegramPollingLoop` treats any non-`not_found`/non-`error` outcome as resolved branch, risking dispatch with null tenant/user on malformed backend payload.
   - This is a correctness/safety contract gap for MAJOR lane validation (foundation contract should be explicit and closed).

7. **112/112 claim cannot be independently reproduced in this runner (CONSTRAINED).**
   - Attempted full 8-phase regression command.
   - Blocked by missing dependencies (`fastapi`) and unresolved package import path in current environment.
   - Therefore, pass-count claim remains unverified in this environment.

## Score Breakdown
- Scope adherence: 24/25
- Backend boundary safety: 24/25
- Runtime integration correctness: 20/25
- Evidence reproducibility in current runner: 14/25

**Total: 82/100**

## Critical Issues
- Critical: 0
- High: 1
  - Unknown outcome normalization gap in backend client/runtime contract.
- Medium: 1
  - Claimed 112/112 pass not reproducible in this runner due dependency/env constraints.

## Status
**CONDITIONAL**

## PR Gate Result
- Merge is **not blocked for architectural scope drift**.
- Merge is **conditionally held** pending one required contract hardening fix and one reproducible test-evidence rerun in dependency-complete environment.

## Broader Audit Finding
- Foundation boundary is clean and intentionally narrow.
- Tenant isolation is preserved at lookup boundary.
- No evidence of hidden scope expansion into auth productization/execution domains.

## Reasoning
Given declared claim level (FOUNDATION), broad product omissions are acceptable and truthful. However, the identity outcome contract is a core safety boundary for dispatch routing. Accepting unexpected outcomes and implicitly routing toward dispatch without strict normalization is a material integration gap for this lane and must be fixed prior to approval.

## Fix Recommendations
1. In `CrusaderBackendClient.resolve_telegram_identity()`, normalize response outcome strictly:
   - Allowed: `resolved`, `not_found`, `error`
   - Any unknown value -> `error`
2. In `TelegramPollingLoop`, only enter resolved dispatch branch when:
   - `resolution.outcome == "resolved"` AND
   - `resolution.tenant_id` and `resolution.user_id` are non-empty strings
   - Otherwise send `_REPLY_IDENTITY_ERROR` and skip dispatch.
3. Re-run the claimed 112-test regression suite in dependency-complete environment and attach exact command output artifact.

## Out-of-scope Advisory
- Pre-auth identity route rate limiting / abuse controls remain a follow-up hardening lane (not blocker for declared foundation claim).

## Deferred Minor Backlog
- None deferred in this validation pass.

## Telegram Visual Preview
- Registered Telegram user issuing `/start`: identity resolved via backend, command dispatched under real tenant/user, reply sent.
- Unregistered Telegram user issuing `/start`: receives explicit not-registered reply, dispatch skipped.
- Identity backend error/exception: receives identity-error reply, dispatch skipped.
- Non-command Telegram message: ignored (no identity lookup, no dispatch).
