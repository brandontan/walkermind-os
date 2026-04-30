# Phase 8.9 Post-Merge Truth Sync + Phase 8.10 Telegram Identity Resolution Foundation

**Date:** 2026-04-19 15:52
**Branch:** claude/phase8-10-telegram-identity-ePWJP
**Validation Tier:** MAJOR (Part B); MINOR (Part A)
**Claim Level:** FOUNDATION
**Validation Target:** TelegramIdentityService resolve contract; get_user_by_external_id storage/service boundary; GET /auth/telegram-identity/{telegram_user_id} route; CrusaderBackendClient.resolve_telegram_identity HTTP path; TelegramIdentityResolver Protocol; TelegramPollingLoop resolved/not_found/error branching; bot.py identity_resolver wiring
**Not in Scope:** full polished Telegram account-link UX, broad command suite beyond /start, OAuth rollout, RBAC rollout, delegated signing lifecycle, exchange execution rollout, portfolio engine rollout, full web identity rollout, production-grade cross-client identity linking orchestration
**Suggested Next:** SENTINEL validation required before merge (Tier: MAJOR)

---

## 1. What Was Built

### Part A — Phase 8.9 Post-Merge Truth Sync (MINOR)

- `PROJECT_STATE.md` updated: Phase 8.9 moved from IN PROGRESS to COMPLETED (SENTINEL CONDITIONAL gate satisfied via `phase8-9_02_pytest-evidence-pass.md`, 94/94 pass). Phase 8.10 added to IN PROGRESS. NEXT PRIORITY updated to SENTINEL for Phase 8.10. Timestamp advanced from `2026-04-19 15:21` to `2026-04-19 15:52`.
- `ROADMAP.md` updated: Phase 8.9 status changed from `🚧 In Progress — SENTINEL validation required before merge` to `✅ Done (merged. SENTINEL CONDITIONAL gate satisfied via phase8-9_02_pytest-evidence-pass.md, 94/94 pass. PR #608 merged, PR #609 CONDITIONAL satisfied)`; Phase 8.10 checklist section added.
- Stale wording removed: no more "SENTINEL validation required" for Phase 8.9.
- Truthful references preserved:
  - `projects/polymarket/polyquantbot/reports/forge/phase8-9_01_telegram-runtime-loop-foundation.md`
  - `projects/polymarket/polyquantbot/reports/forge/phase8-9_02_pytest-evidence-pass.md`
  - SENTINEL: PR #609 (CONDITIONAL gate satisfied)

### Part B — Phase 8.10 Telegram Identity Resolution Foundation (MAJOR)

**1. Backend Lookup Extension**

- `MultiUserStore.get_user_by_external_id(tenant_id, external_id) -> UserRecord | None` — added to abstract base class
- `PersistentMultiUserStore.get_user_by_external_id` — scans `_users` dict for matching `tenant_id` + `external_id`, returns first match or None
- `InMemoryMultiUserStore.get_user_by_external_id` — same pattern over in-memory `users` dict (used in tests)
- `UserService.get_user_by_external_id(tenant_id, external_id)` — thin delegation to store boundary

**2. TelegramIdentityService (`server/services/telegram_identity_service.py`)**

- `TelegramIdentityResolution` — frozen dataclass: `outcome` (resolved/not_found/error), `tenant_id`, `user_id`, `error_detail`
- `TelegramIdentityService.resolve(telegram_user_id, tenant_id)` — looks up `external_id = "tg_{telegram_user_id}"` in the given tenant via `UserService.get_user_by_external_id`. Returns typed resolution outcome with zero silent failures (exception → error outcome + logged).
- `TELEGRAM_EXTERNAL_ID_PREFIX = "tg_"` — canonical prefix for Telegram-origin external_id values

**3. Backend Identity Route (`server/api/client_auth_routes.py`)**

- `GET /auth/telegram-identity/{telegram_user_id}?tenant_id=...` added to `build_client_auth_router`
- Pre-auth lookup: does not require a session header
- Returns `{"outcome": ..., "tenant_id": ..., "user_id": ...}` — truthful resolution outcomes only
- `build_client_auth_router` signature updated to accept `telegram_identity_service: TelegramIdentityService`

**4. Server Wiring (`server/main.py`)**

- `TelegramIdentityService(user_service=user_service)` instantiated in `create_app()`
- Stored in `app.state.telegram_identity_service`
- Passed into `build_client_auth_router(..., telegram_identity_service=telegram_identity_service)`
- Phase tag advanced from `"8.6"` to `"8.10"`

**5. Client-Side Identity Types (`client/telegram/backend_client.py`)**

- `TelegramIdentityResolution` — frozen dataclass: `outcome`, `tenant_id`, `user_id` (client-side mirror of server type, no `error_detail` field needed client-side)
- `TelegramIdentityOutcome` type alias added
- `CrusaderBackendClient.__init__` updated: new `identity_tenant_id: str = "staging"` parameter — the tenant used for identity lookups
- `CrusaderBackendClient.resolve_telegram_identity(telegram_user_id)` — calls `GET /auth/telegram-identity/{telegram_user_id}?tenant_id={identity_tenant_id}`; maps HTTP 200 response to typed outcome; HTTP failures → outcome=error

**6. TelegramIdentityResolver Protocol + Updated TelegramPollingLoop (`client/telegram/runtime.py`)**

- `TelegramIdentityResolver` Protocol — defines `resolve_telegram_identity(telegram_user_id) -> TelegramIdentityResolution`. `CrusaderBackendClient` satisfies this protocol structurally.
- `_REPLY_NOT_REGISTERED` — user-facing reply for unlinked/unknown Telegram users
- `_REPLY_IDENTITY_ERROR` — user-facing reply for backend resolution errors
- `TelegramPollingLoop.__init__` updated: new `identity_resolver: Optional[TelegramIdentityResolver] = None` parameter
- `TelegramPollingLoop._process_update` updated: when resolver is present, calls `resolve_telegram_identity(from_user_id)` before dispatch:
  - `not_found` → sends `_REPLY_NOT_REGISTERED`, returns (no dispatch)
  - `error` → sends `_REPLY_IDENTITY_ERROR`, returns (no dispatch)
  - resolver exception → sends `_REPLY_IDENTITY_ERROR`, returns (no dispatch)
  - `resolved` → replaces staging `tenant_id`/`user_id` in `TelegramCommandContext` with real backend scope, then dispatches
- Staging fallback preserved: when `identity_resolver=None`, loop behaves identically to Phase 8.9
- `run_polling_loop` updated: accepts `identity_resolver` parameter, passes to `TelegramPollingLoop`
- Phase tag in polling log advanced from `"8.9"` to `"8.10"`

**7. Bot Bootstrap (`client/telegram/bot.py`)**

- `CrusaderBackendClient` construction updated: passes `identity_tenant_id=settings.staging_tenant_id`
- `run_polling_loop` called with `identity_resolver=backend` — `CrusaderBackendClient` satisfies `TelegramIdentityResolver` protocol
- Bootstrap log updated: `identity_resolution="backend"`, `phase="8.10"`

**8. Targeted Phase 8.10 Tests (`tests/test_phase8_10_telegram_identity_20260419.py`)**

18 targeted tests covering:
- `TelegramIdentityService`: resolved, not_found, wrong_tenant (not_found), empty telegram_user_id (error), empty tenant_id (error), store exception (error)
- `CrusaderBackendClient.resolve_telegram_identity`: HTTP 200 resolved, HTTP 200 not_found, HTTP error/exception, empty telegram_user_id
- `TelegramPollingLoop` with resolver: resolved dispatches with real tenant/user, resolved sends dispatch reply, not_found sends unregistered reply + no dispatch, error sends identity_error reply + no dispatch, resolver exception sends identity_error reply + no dispatch, no resolver uses staging fallback, resolver called with correct from_user_id, resolver skipped for non-command messages

---

## 2. Current System Architecture (Relevant Slice)

```
Telegram Bot API (long-poll)
        |
        v
HttpTelegramAdapter.get_updates(offset)
  -> GET /bot{token}/getUpdates
  -> _parse_single_update(raw) -> TelegramInboundUpdate
        |
        v
TelegramPollingLoop._process_update(update)
        |
        v
extract_command_context(update, staging_tenant_id, staging_user_id)
  text.startswith('/') -> TelegramCommandContext (with placeholder identity)
  else -> None (skipped)
        |
        v  [if identity_resolver is not None]
CrusaderBackendClient.resolve_telegram_identity(from_user_id)
  -> GET /auth/telegram-identity/{telegram_user_id}?tenant_id={identity_tenant_id}
  -> TelegramIdentityResolution(outcome, tenant_id, user_id)

  outcome == "not_found" -> send _REPLY_NOT_REGISTERED, return
  outcome == "error"     -> send _REPLY_IDENTITY_ERROR, return
  outcome == "resolved"  -> replace ctx.tenant_id, ctx.user_id with real backend scope
        |
        v  [identity resolved or no resolver (staging fallback)]
TelegramDispatcher.dispatch(ctx)
  ctx.command == "/start" -> _dispatch_start() -> handle_start()
  else -> DispatchResult(outcome="unknown_command", ...)
        |
        v
DispatchResult.reply_text -> HttpTelegramAdapter.send_reply(chat_id, reply_text)

Backend identity resolution:
  GET /auth/telegram-identity/{telegram_user_id}?tenant_id=...
  -> TelegramIdentityService.resolve(telegram_user_id, tenant_id)
  -> UserService.get_user_by_external_id(tenant_id, "tg_{telegram_user_id}")
  -> UserRecord lookup in PersistentMultiUserStore._users
  -> outcome: resolved / not_found / error

Identity contract (Phase 8.10):
  registered user:   tenant_id + user_id from real backend UserRecord
  unregistered user: _REPLY_NOT_REGISTERED reply, no dispatch
  error:             _REPLY_IDENTITY_ERROR reply, no dispatch
  no resolver wired: staging contract preserved (backward compat)

Persistence backbone (unchanged from Phase 8.6-8.9):
  PersistentMultiUserStore  (multi_user.json)    <- restart-safe ownership
  PersistentSessionStore    (sessions.json)      <- restart-safe sessions
  PersistentWalletLinkStore (wallet_links.json)  <- restart-safe wallet-links
```

---

## 3. Files Created / Modified (Full Repo-Root Paths)

### Created
- `projects/polymarket/polyquantbot/server/services/telegram_identity_service.py`
- `projects/polymarket/polyquantbot/tests/test_phase8_10_telegram_identity_20260419.py`
- `projects/polymarket/polyquantbot/reports/forge/phase8-10_01_telegram-identity-resolution-foundation.md` (this file)

### Modified
- `projects/polymarket/polyquantbot/server/storage/multi_user_store.py` (get_user_by_external_id added to abstract base + PersistentMultiUserStore)
- `projects/polymarket/polyquantbot/server/storage/in_memory_store.py` (get_user_by_external_id added to InMemoryMultiUserStore)
- `projects/polymarket/polyquantbot/server/services/user_service.py` (get_user_by_external_id delegation)
- `projects/polymarket/polyquantbot/server/api/client_auth_routes.py` (GET /auth/telegram-identity route + TelegramIdentityService param)
- `projects/polymarket/polyquantbot/server/main.py` (TelegramIdentityService wiring + phase 8.10 tag)
- `projects/polymarket/polyquantbot/client/telegram/backend_client.py` (TelegramIdentityResolution type + identity_tenant_id + resolve_telegram_identity method)
- `projects/polymarket/polyquantbot/client/telegram/runtime.py` (TelegramIdentityResolver Protocol + reply constants + TelegramPollingLoop identity resolver integration + run_polling_loop signature)
- `projects/polymarket/polyquantbot/client/telegram/bot.py` (identity_tenant_id + identity_resolver=backend + phase 8.10 tag)
- `PROJECT_STATE.md` (Phase 8.9 COMPLETED + Phase 8.10 IN PROGRESS + timestamp)
- `ROADMAP.md` (Phase 8.9 Done + Phase 8.10 checklist added + timestamp)

---

## 4. What Is Working

**Backend storage lookup (unit-tested via InMemoryMultiUserStore):**
- `get_user_by_external_id(tenant_id="t1", external_id="tg_12345678")` returns correct `UserRecord` when user exists
- Returns `None` when no matching user in tenant
- Returns `None` when user exists in different tenant (correct isolation)

**TelegramIdentityService (unit-tested, 6 tests):**
- Resolved: known telegram_user_id → `TelegramIdentityResolution(outcome="resolved", tenant_id, user_id)`
- Not found: unknown telegram_user_id → `outcome="not_found"`
- Wrong tenant: existing user in different tenant → `outcome="not_found"` (isolation preserved)
- Empty telegram_user_id → `outcome="error"` with error_detail
- Empty tenant_id → `outcome="error"` with error_detail
- Store exception → `outcome="error"`, exception logged, not swallowed

**CrusaderBackendClient.resolve_telegram_identity (unit-tested, 4 tests):**
- HTTP 200 resolved → `TelegramIdentityResolution(outcome="resolved", tenant_id, user_id)`
- HTTP 200 not_found → `TelegramIdentityResolution(outcome="not_found")`
- HTTP connection error → `TelegramIdentityResolution(outcome="error")`
- Empty telegram_user_id → `TelegramIdentityResolution(outcome="error")` (no HTTP call)

**TelegramPollingLoop with resolver (unit-tested, 8 tests):**
- Resolved identity → `TelegramDispatcher.dispatch()` called with real `tenant_id`/`user_id`
- Resolved identity → dispatch `reply_text` sent via adapter
- Not found → `_REPLY_NOT_REGISTERED` sent, dispatch NOT called
- Error → `_REPLY_IDENTITY_ERROR` sent, dispatch NOT called
- Resolver exception → `_REPLY_IDENTITY_ERROR` sent, dispatch NOT called
- No resolver (None) → staging fallback, dispatch called with `tenant_id="staging"`, `user_id="staging"`
- Resolver called with correct `from_user_id`
- Non-command message → resolver NOT called, dispatch NOT called, no reply

**Full pytest evidence (112/112 pass):**
```
platform linux -- Python 3.11.15, pytest-9.0.2, pluggy-1.6.0

Phase 8.10 identity resolution tests (18/18):   all PASSED
Phase 8.9 regression (17/17):                   all PASSED
Phase 8.8 regression (15/15):                   all PASSED
Phase 8.7 regression (16/16):                   all PASSED
Phase 8.6 regression (13/13):                   all PASSED
Phase 8.5 regression (13/13):                   all PASSED
Phase 8.4 regression (12/12):                   all PASSED
Phase 8.1 regression  (8/8):                    all PASSED

112 passed in 6.28s
```

---

## 5. Known Issues

- `TelegramIdentityService.resolve` performs a linear scan of all users in the store for `get_user_by_external_id`. For the FOUNDATION scope with local-file JSON persistence, this is acceptable. A database index on `(tenant_id, external_id)` is the production follow-up.
- `resolve_telegram_identity` in `CrusaderBackendClient` uses the configured `identity_tenant_id` for all lookups. Multi-tenant routing where the Telegram user could belong to any tenant is a follow-up lane.
- No automatic user registration on first `/start` from an unknown Telegram user. `not_found` users receive an unregistered reply. Self-service Telegram onboarding/account-linking UX is explicitly excluded from this scope.
- `GET /auth/telegram-identity/{telegram_user_id}` route does not require authentication. It is a pre-auth lookup surface. Rate limiting and abuse protection are follow-up hardening lanes.
- `Unknown config option: asyncio_mode` pytest warning is pre-existing hygiene backlog (non-runtime, carried forward).

---

## 6. What Is Next

SENTINEL validation required for Phase 8.10 before merge.

Source: `projects/polymarket/polyquantbot/reports/forge/phase8-10_01_telegram-identity-resolution-foundation.md`
Tier: MAJOR
Claim Level: FOUNDATION

Validation Target:
- `TelegramIdentityService.resolve` outcomes: resolved / not_found / error
- `get_user_by_external_id` storage boundary correctness and tenant isolation
- `GET /auth/telegram-identity/{telegram_user_id}` route returns correct outcome
- `CrusaderBackendClient.resolve_telegram_identity` HTTP mapping correctness
- `TelegramPollingLoop` resolved/not_found/error/exception branching
- Staging fallback preserved when `identity_resolver=None`
- Phase 8.9 regression: 17/17 pass preserved
- Full 112/112 regression pass

After SENTINEL validates and COMMANDER approves merge, the next public-readiness lanes are:
- Telegram account-link onboarding: self-service flow for unregistered users to register with the bot
- `/status`, `/help`, and additional commands
- Rate limiting on identity lookup route
- Production database index for `(tenant_id, external_id)` lookup
- Multi-tenant identity routing

---

**Validation Tier:** MAJOR (Part B) / MINOR (Part A — truth sync only)
**Claim Level:** FOUNDATION
**Validation Target:** TelegramIdentityService resolve contract; storage lookup boundary; identity route; CrusaderBackendClient HTTP path; TelegramIdentityResolver Protocol; TelegramPollingLoop resolver branching; bot.py wiring
**Not in Scope:** full Telegram account-link UX, broad command suite, OAuth, RBAC, delegated signing lifecycle, exchange execution, portfolio engine, full web identity, production-grade cross-client identity linking
**Suggested Next:** SENTINEL validation required before merge
