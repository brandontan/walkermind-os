# Phase 8.4 — Client Auth Handoff / Wallet-Link Foundation

**Date:** 2026-04-19 10:45
**Branch:** claude/phase8-client-auth-wallet-link-fV4Qd
**Validation Tier:** MAJOR
**Claim Level:** FOUNDATION
**Validation Target:** client auth handoff contract + wallet-link ownership enforcement
**Not in Scope:** full Telegram login UX, full web login UX, OAuth rollout, production token rotation, full RBAC, delegated signing lifecycle, full wallet lifecycle orchestration, exchange signing rollout, on-chain settlement rollout, broad portfolio engine work
**Suggested Next:** SENTINEL validation required before merge

---

## 1. What Was Built

### Part A — Phase 8.3 Post-Merge Truth Sync

- `PROJECT_STATE.md` and `ROADMAP.md` updated to reflect Phase 8.3 as merged baseline
- Stale "mergeable / COMMANDER review pending" wording removed
- Phase 8.3 checklist in `ROADMAP.md` marked `Done (Merged via PR #596)`
- `NEXT PRIORITY` updated to point to Phase 8.4 SENTINEL validation

### Part B — Phase 8.4 Client Auth Handoff / Wallet-Link Foundation

Two real backend foundations added over the Phase 8.3 persistent session backbone:

**1. Client Auth Handoff Contract (`server/core/client_auth_handoff.py`)**

A minimal deterministic contract for trusted client-to-backend identity handoff:
- Accepts `client_type` (telegram / web) and `client_identity_claim` (string claim, e.g. telegram_user_id)
- Validates structural contract: known client_type, non-empty claim, non-empty scope
- Returns `ClientHandoffValidation` with outcome + auth_method mapping
- Cryptographic / UX-level identity verification is explicitly deferred (future production gate)

**2. Client Auth Route (`POST /auth/handoff`)**

Exposes the handoff contract as a backend endpoint:
- Takes `ClientHandoffRequestBody` (client_type, client_identity_claim, tenant_id, user_id, ttl_seconds)
- Validates handoff contract before touching session service
- Delegates to existing `AuthSessionService.issue_session()` with `auth_method="telegram"` or `"web"`
- Returns `SessionIssueResponse` (identity + session + scope)

**3. Wallet-Link Schema + Storage + Service**

Minimal user-owned external wallet address record layer:
- `WalletLinkRecord`: link_id, tenant_id, user_id, wallet_address, chain_id, link_type, linked_at, status
- `WalletLinkStore`: in-memory dict boundary with user-scoped list query
- `WalletLinkService`: create_link + list_links — both scoped to authenticated user
- Wallet-link records are tenant/user-owned and isolated — no cross-user reads

**4. Authenticated Wallet-Link Routes**

Protected routes under `/auth/wallet-links`:
- `POST /auth/wallet-links` — creates wallet-link record for the authenticated user scope
- `GET /auth/wallet-links` — lists wallet-link records for the authenticated user scope only
- Both routes enforce `get_authenticated_scope` dependency — no session → 403
- Cross-user denial: scope is derived from session, not from request body

**5. App Wiring**

`server/main.py` wired to include `WalletLinkStore`, `WalletLinkService`, and `client_auth_router`.

---

## 2. Current System Architecture (Relevant Slice)

```
Client (Telegram / Web)
       |
       v
POST /auth/handoff
       |
       v
ClientHandoffContract validation (core/client_auth_handoff.py)
  [client_type in {telegram, web}]
  [client_identity_claim non-empty]
  [tenant_id + user_id non-empty]
       |
       v
AuthSessionService.issue_session()
  [user exists in InMemoryMultiUserStore]
  [tenant_id matches user.tenant_id]
  [session persisted via PersistentSessionStore]
       |
       v
SessionIssueResponse (identity + session + scope)
       |
       v
Client uses session headers for authenticated routes

Authenticated client
       |
       v
POST /auth/wallet-links  (or GET /auth/wallet-links)
       |
       v
get_authenticated_scope dependency
  [X-Session-Id, X-Auth-Tenant-Id, X-Auth-User-Id headers]
  [session must exist + be active + not expired + headers must match]
       |
       v
WalletLinkService.create_link() or .list_links()
  [scope.tenant_id + scope.user_id bound to authenticated session]
  [records stored in WalletLinkStore]
       |
       v
WalletLinkRecord (user-owned, isolated)
```

Ownership chain is unbroken:
- Handoff validates user exists in multi-user store
- Session derives from existing auth backbone (Phase 8.3)
- Wallet-link scope is derived from session, not request body — no scope injection possible
- Cross-user reads return empty list (correct — user B has no access to user A's records)
- Cross-user create with tampered session headers returns 403

---

## 3. Files Created / Modified (Full Repo-Root Paths)

### Created
- `projects/polymarket/polyquantbot/server/schemas/wallet_link.py`
- `projects/polymarket/polyquantbot/server/storage/wallet_link_store.py`
- `projects/polymarket/polyquantbot/server/services/wallet_link_service.py`
- `projects/polymarket/polyquantbot/server/core/client_auth_handoff.py`
- `projects/polymarket/polyquantbot/server/api/client_auth_routes.py`
- `projects/polymarket/polyquantbot/tests/test_phase8_4_client_auth_wallet_link_20260419.py`
- `projects/polymarket/polyquantbot/reports/forge/phase8-4_01_client-auth-wallet-link-foundation.md` (this file)

### Modified
- `projects/polymarket/polyquantbot/server/main.py` (added WalletLinkStore + WalletLinkService + client_auth_router wiring)
- `PROJECT_STATE.md` (Part A truth sync + Part B update)
- `ROADMAP.md` (Phase 8.3 marked Done, Phase 8.4 checklist added)

---

## 4. What Is Working

**Client Auth Handoff Contract (pure function, unit tested):**
- `validate_client_handoff` returns `valid` + correct `auth_method` for telegram / web
- Rejects unsupported client types (e.g. "discord")
- Rejects empty identity claim (whitespace-only)
- Rejects empty tenant_id or user_id

**Client Auth Handoff Route:**
- `POST /auth/handoff` issues real session for a known user with auth_method="telegram" or "web"
- Returns 400 for unknown user (user not found in InMemoryMultiUserStore)
- Returns 400 for unsupported client_type
- Session is persisted via PersistentSessionStore (restart-safe)

**Wallet-Link Routes:**
- `POST /auth/wallet-links` creates a scoped wallet-link record bound to authenticated user
- `GET /auth/wallet-links` lists only the authenticated user's wallet-links
- Missing / invalid session returns 403 (authenticated scope dependency enforced)
- Cross-user session headers return 403 (tampered user_id rejected by session validation)
- User B cannot see User A's wallet-links via list route (returns empty list — correct isolation)

**Regression:**
- All 13 prior tests (Phase 8.1 + runtime surface) continue to pass — 0 regressions

**Test evidence (12/12 pass):**
```
platform linux -- Python 3.11.15, pytest-9.0.2, pluggy-1.6.0
rootdir: /home/user/walker-ai-team
configfile: pytest.ini
plugins: anyio-4.13.0
collected 12 items

test_handoff_validates_known_telegram_client             PASSED
test_handoff_validates_known_web_client                  PASSED
test_handoff_rejects_unsupported_client_type             PASSED
test_handoff_rejects_empty_claim                         PASSED
test_handoff_rejects_empty_scope                         PASSED
test_client_handoff_issues_session_for_known_user        PASSED
test_client_handoff_rejects_unknown_user                 PASSED
test_client_handoff_rejects_unsupported_client_type_via_route PASSED
test_wallet_link_create_and_read_for_authenticated_user  PASSED
test_wallet_link_requires_authenticated_session          PASSED
test_wallet_link_cross_user_isolation                    PASSED
test_wallet_link_cross_tenant_session_denied             PASSED

12 passed, 1 warning in 1.40s
```

---

## 5. Known Issues

- `WalletLinkStore` is in-memory only — wallet-link records are not restart-safe at this foundation stage (consistent with Phase 8.1 multi-user store; persistent wallet-link storage is a follow-up lane)
- `client_identity_claim` is structurally validated only — no cryptographic verification of Telegram or web identity (explicit deferred gate; claimed in FOUNDATION scope)
- `auth_method` in `SessionCreateRequest` accepts "telegram" and "web" as typed literals — the `# type: ignore[arg-type]` comment in `client_auth_routes.py` is needed because `validation.auth_method` is `str`, not `AuthMethod` literal; safe at runtime since `validate_client_handoff` only returns "telegram" or "web" on `valid` outcome
- `Unknown config option: asyncio_mode` warning in pytest is pre-existing hygiene backlog (carried from Phase 8.3)

---

## 6. What Is Next

SENTINEL validation required for Phase 8.4 before merge.

Source: `projects/polymarket/polyquantbot/reports/forge/phase8-4_01_client-auth-wallet-link-foundation.md`
Tier: MAJOR

Validation Target:
- client auth handoff contract enforcement (structural validation, reject paths)
- wallet-link ownership enforcement (session dependency, cross-user isolation)
- authenticated wallet-link create/read/deny flows
- regression coverage on Phase 8.1 / runtime surface tests

After SENTINEL validates and COMMANDER approves merge, the next public-readiness lanes are:
- Persistent wallet-link storage (restart-safe wallet-link records)
- Telegram bot handler thin integration (client-side handoff surface, not this lane)
- RBAC / permission scope (further production hardening)

---

**Validation Tier:** MAJOR
**Claim Level:** FOUNDATION
**Validation Target:** client auth handoff contract + wallet-link ownership enforcement under authenticated session scope
**Not in Scope:** full Telegram login UX, full web login UX, OAuth, production token rotation, full RBAC, delegated signing, wallet lifecycle, exchange/on-chain rollout, portfolio engine
**Suggested Next:** SENTINEL validation required before merge
