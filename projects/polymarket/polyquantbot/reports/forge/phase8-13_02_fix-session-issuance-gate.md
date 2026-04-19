# Phase 8.13 Fix — Remove Auto-Promotion in Telegram Session Issuance

**Date:** 2026-04-19 23:28
**Branch:** claude/fix-telegram-session-issuance-zGD86
**Fixes:** PR #616 — SENTINEL BLOCKED finding from PR #617

## 1. What was built

Removed the auto-promotion path from `TelegramSessionIssuanceService.issue()` that
silently mutated `pending_confirmation -> active` before issuing a session. The service
now enforces a strict activation gate: only users with `activation_status == "active"`
receive a backend session. All other users receive `rejected` with zero state mutation.

Additionally ported all Phase 8.13 runtime wiring from PR #616 (runtime session_issuer
protocol, backend_client session issuance method, client_auth route, and main.py bootstrap)
since the working branch predates that PR and required the full Phase 8.13 surface.

### Contract enforced

| User state | Outcome | Side effect |
|---|---|---|
| `active` | `session_issued` | new backend session created |
| `pending_confirmation` | `rejected` | no state change, no session |
| user not linked | `rejected` | no state change, no session |
| settings missing | `error` | no state change |

## 2. Current system architecture (relevant slice)

Telegram `/start` lifecycle after this fix:

```
1. TelegramPollingLoop receives /start update
2. TelegramIdentityResolver -> resolved / not_found / error
   not_found -> TelegramOnboardingInitiator.start_telegram_onboarding()
   resolved  -> next step
3. TelegramActivationConfirmer.confirm_telegram_activation()  [Phase 8.12]
   pending_confirmation -> activated (state change here, NOT in issuance)
   already_active -> continue
   activated -> reply ACTIVATED, stop (user must /start again)
4. TelegramSessionIssuer.issue_telegram_session()             [Phase 8.13 — FIXED]
   active user  -> session_issued  (strict gate, no mutation)
   non-active   -> rejected        (strict gate, no mutation)
5. Reply mapped from issuance outcome
```

Phase 8.12 `TelegramActivationService.confirm()` is the sole owner of the
`pending_confirmation -> active` state transition. Phase 8.13 session issuance
only reads activation state and never writes it.

## 3. Files created / modified (full repo-root paths)

### Created
- `projects/polymarket/polyquantbot/server/services/telegram_session_issuance_service.py`
- `projects/polymarket/polyquantbot/tests/test_phase8_13_telegram_session_issuance_20260419.py`
- `projects/polymarket/polyquantbot/reports/forge/phase8-13_02_fix-session-issuance-gate.md`

### Modified
- `projects/polymarket/polyquantbot/client/telegram/backend_client.py`
  (added TelegramSessionIssuanceOutcome, TelegramSessionIssuanceResult, issue_telegram_session())
- `projects/polymarket/polyquantbot/client/telegram/runtime.py`
  (added TelegramSessionIssuer Protocol, session_issuer in TelegramPollingLoop and run_polling_loop,
   added _REPLY_SESSION_ISSUED and _REPLY_ALREADY_ACTIVE_SESSION_ISSUED, updated phase to 8.13)
- `projects/polymarket/polyquantbot/server/api/client_auth_routes.py`
  (added TelegramSessionIssueBody, added telegram_session_issuance_service param,
   added POST /auth/telegram-onboarding/session-issue route)
- `projects/polymarket/polyquantbot/server/main.py`
  (import and wire TelegramSessionIssuanceService, updated phase to 8.13)
- `PROJECT_STATE.md`

## 4. What is working

- Strict activation gate enforced: `activation_status == "active"` required for session issuance.
- `pending_confirmation` users return `rejected` with zero state mutation (confirmed by test).
- Active users receive `session_issued` with a real backend session token.
- Calling `issue()` multiple times on an active user is always allowed (`session_issued` each time).
- `TelegramActivationService.confirm()` remains the sole owner of the `pending -> active` transition.
- All runtime reply mappings preserved (`session_issued`, `already_active_session_issued`, `rejected`, `error`).
- Full pytest gate: **148/148 pass** across Phase 8.1–8.13 test suites.
- All touched files pass `python3 -m py_compile`.

## 5. Known issues

- `already_active_session_issued` is present in the outcome type and the runtime reply map for
  completeness, but the current service always returns `session_issued` for active users. A future
  pass could distinguish "first session" vs "subsequent session" by querying existing session state.
- Integration tests use `pytest.importorskip("fastapi.testclient")` as runtime dependency guard.
- `asyncio_mode` warning is a pre-existing non-runtime hygiene item (carried forward).

## 6. What is next

- COMMANDER reviews fix evidence and decides whether to update PR #616 or merge this branch.
- SENTINEL PR #617 BLOCKED finding is resolved — reevaluation can proceed.
- No ROADMAP.md change required (no milestone-level truth change from this fix).

---

Validation Tier   : MAJOR (session issuance lifecycle — activation gate correctness)
Claim Level       : NARROW INTEGRATION
Validation Target : TelegramSessionIssuanceService.issue() strict gate enforcement;
                    pending_confirmation non-mutation; active-user session issuance;
                    tenant isolation; runtime reply mapping; integration route behavior
Not in Scope      : full Telegram UX, OAuth/RBAC, portfolio engine, exchange execution,
                    broader activation lifecycle outside Phase 8.12-8.13 boundary
Suggested Next    : COMMANDER review — merge decision for PR #616 / this branch
