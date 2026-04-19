# Phase 8.10 Post-Merge Truth Sync + Phase 8.11 Telegram Onboarding / Account-Link Foundation

**Date:** 2026-04-19 20:16  
**Branch:** feature/phase8-11-telegram-onboarding-account-link-foundation-2026-04-19

## 1. What was built

### Part A — Phase 8.10 closeout (truth sync)
- Synced `PROJECT_STATE.md` and `ROADMAP.md` to close stale "pending merge/validation" wording for Phase 8.10 and reflect merged-truth status.
- Preserved Phase 8.10 reference continuity:
  - `projects/polymarket/polyquantbot/reports/forge/phase8-10_01_telegram-identity-resolution-foundation.md`
  - `projects/polymarket/polyquantbot/reports/forge/phase8-10_02_pytest-evidence-pass.md`
  - `projects/polymarket/polyquantbot/reports/sentinel/phase8-10_01_telegram-identity-validation-pr610.md`

### Part B — Phase 8.11 onboarding/account-link foundation
- Added `TelegramOnboardingService` with narrow outcomes:
  - `onboarded` -> creates minimal user record with `external_id=tg_{telegram_user_id}`
  - `already_linked` -> existing user matched by `(tenant_id, external_id)`
  - `rejected` -> invalid input boundary
  - `error` -> storage/service exception boundary
- Added backend route:
  - `POST /auth/telegram-onboarding/start`
- Added client contract:
  - `CrusaderBackendClient.start_telegram_onboarding()`
- Extended Telegram runtime:
  - unresolved identity (`not_found`) now invokes onboarding initiator and maps safe reply outcomes (`onboarded`, `already_linked`, `rejected`, `error`)
  - resolved identity flow from Phase 8.10 remains unchanged

## 2. Current system architecture (relevant slice)

`TelegramPollingLoop` now follows:
1. resolve identity via `resolve_telegram_identity()`
2. if `resolved` -> dispatch unchanged over real tenant/user scope
3. if `not_found` -> call `start_telegram_onboarding()`
4. map onboarding result to safe Telegram reply and stop dispatch for that update

Backend onboarding path:
1. `POST /auth/telegram-onboarding/start`
2. `TelegramOnboardingService.start(telegram_user_id, tenant_id)`
3. lookup existing user by `external_id=tg_{telegram_user_id}`
4. if missing -> create `UserRecord` (persistent via existing `PersistentMultiUserStore`)
5. return typed onboarding outcome

## 3. Files created / modified (full repo-root paths)

### Created
- `projects/polymarket/polyquantbot/server/services/telegram_onboarding_service.py`
- `projects/polymarket/polyquantbot/tests/test_phase8_11_telegram_onboarding_20260419.py`
- `projects/polymarket/polyquantbot/reports/forge/phase8-11_01_telegram-onboarding-account-link-foundation.md`

### Modified
- `projects/polymarket/polyquantbot/server/api/client_auth_routes.py`
- `projects/polymarket/polyquantbot/server/main.py`
- `projects/polymarket/polyquantbot/client/telegram/backend_client.py`
- `projects/polymarket/polyquantbot/client/telegram/runtime.py`
- `projects/polymarket/polyquantbot/client/telegram/bot.py`
- `PROJECT_STATE.md`
- `ROADMAP.md`

## 4. What is working

- Unresolved Telegram users no longer receive only dead-end rejection; onboarding foundation now starts from runtime not_found branch.
- Onboarding create path persists created user mapping in multi-user store.
- Already-linked users are detected deterministically by `(tenant_id, external_id)`.
- Rejected and error paths return safe reply behavior without runtime crash.
- Phase 8.10 resolver/dispatch behavior remains preserved.

## 5. Known issues

- This lane is intentionally not full account-link productization (no OAuth/RBAC/multi-client UX).
- Onboarding currently creates minimal user-only linkage foundation; account/wallet lifecycle remains follow-up.
- Pre-auth onboarding route currently has no rate limiting in this lane.

## 6. What is next

- MAJOR validation handoff to SENTINEL for:
  - onboarding route/service behavior
  - runtime not_found onboarding reply mapping
  - persistence/isolation proof
  - Phase 8.10 regression continuity

Validation declaration:

Validation Tier   : MAJOR (with included MINOR truth sync)  
Claim Level       : FOUNDATION  
Validation Target : Phase 8.11 Telegram onboarding/account-link foundation only (unresolved `/start` path, backend onboarding contract, persistence boundary, outcome mapping, tests)  
Not in Scope      : full Telegram onboarding UX, OAuth, RBAC, delegated signing lifecycle, exchange execution rollout, portfolio rollout, full web onboarding  
Suggested Next    : SENTINEL validation, then COMMANDER review
