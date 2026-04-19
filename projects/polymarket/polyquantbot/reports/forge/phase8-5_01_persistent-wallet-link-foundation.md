# Phase 8.5 — Persistent Wallet-Link Storage / Lifecycle Foundation

**Date:** 2026-04-19 11:28
**Branch:** claude/phase8-5-wallet-link-persistence-ExuR9
**Validation Tier:** MAJOR
**Claim Level:** FOUNDATION
**Validation Target:** persistent wallet-link storage boundary + minimal unlink lifecycle + authenticated ownership enforcement
**Not in Scope:** full wallet lifecycle orchestration, delegated signing lifecycle, exchange signing rollout, on-chain settlement rollout, full RBAC, OAuth rollout, production token rotation platform, broad portfolio engine work, full database migration platform
**Suggested Next:** SENTINEL validation required before merge

---

## 1. What Was Built

### Part A — Phase 8.4 Post-Merge Truth Sync

- `PROJECT_STATE.md` updated: Phase 8.4 moved from pending-COMMANDER to confirmed merged; Phase 8.5 moved from NOT STARTED to IN PROGRESS; NEXT PRIORITY updated to SENTINEL for Phase 8.5
- `ROADMAP.md` updated: Phase 8.4 section status changed from `🚧 In Progress — SENTINEL validation required before merge` to `✅ Done (Merged via PR #598)`; Phase 8.5 checklist section added

### Part B — Phase 8.5 Persistent Wallet-Link Storage / Lifecycle Foundation

**1. Persistent Wallet-Link Storage Boundary (`server/storage/wallet_link_store.py`)**

Refactored from single concrete in-memory class to abstract base + persistent implementation:

- `WalletLinkStore` — abstract base class with `put_link`, `get_link`, `list_links_for_user`, `set_link_status` (SessionStore pattern)
- `WalletLinkStorageError` — typed exception for storage read/write failures
- `PersistentWalletLinkStore` — local-file JSON storage with:
  - Deterministic atomic overwrite via temp-file replace (same pattern as `PersistentSessionStore`)
  - `_load_from_disk()` on init — restart-safe record recovery
  - `_persist_to_disk()` on every write — format version 1, sorted by link_id
  - `set_link_status()` — lifecycle state transition with persistence
  - Configurable path via `CRUSADER_WALLET_LINK_STORAGE_PATH` env var

**2. Wallet-Link Lifecycle Methods (`server/services/wallet_link_service.py`)**

Added two error classes and one lifecycle method to `WalletLinkService`:
- `WalletLinkNotFoundError` — raised when link_id not in store
- `WalletLinkOwnershipError` — raised when authenticated user does not own the record
- `unlink_link(scope, link_id)` — ownership-enforced `active → unlinked` transition; delegates to `store.set_link_status`

**3. Unlink Route (`server/api/client_auth_routes.py`)**

Added one authenticated route to the existing client auth router:
- `PATCH /auth/wallet-links/{link_id}/unlink`
  - Requires valid authenticated session via `get_authenticated_scope` dependency
  - Returns 404 if link_id not found
  - Returns 403 if link belongs to a different user
  - Returns 200 with updated `WalletLinkRecord` on success

**4. App Wiring (`server/main.py`)**

- Replaced `WalletLinkStore()` (in-memory) with `PersistentWalletLinkStore(storage_path=wallet_link_storage_path)`
- Added `CRUSADER_WALLET_LINK_STORAGE_PATH` env var (default: `/tmp/crusaderbot/runtime/wallet_links.json`)
- Added `wallet_link_storage_path` to `app.state` for observability
- Phase log updated to `8.5`

---

## 2. Current System Architecture (Relevant Slice)

```
Client (Telegram / Web)
        |
        v
POST /auth/handoff
        |
        v
AuthSessionService.issue_session()
        |
        v
PersistentSessionStore (sessions.json) ← restart-safe

Authenticated client
        |
        v
POST /auth/wallet-links             create — owned by authenticated user
GET  /auth/wallet-links             list — scoped to authenticated user
PATCH /auth/wallet-links/{id}/unlink  lifecycle: active -> unlinked
        |
        v
WalletLinkService
  create_link  -> PersistentWalletLinkStore.put_link    -> disk write
  list_links   -> PersistentWalletLinkStore.list_links_for_user
  unlink_link  -> ownership check -> .set_link_status("unlinked") -> disk write
        |
        v
PersistentWalletLinkStore (wallet_links.json) ← restart-safe
  _load_from_disk()  on init
  _persist_to_disk() on every mutation  (atomic temp-file replace)
  JSON format: { "version": 1, "records": [...] }
```

Ownership chain is unbroken:
- Session scope is derived from authenticated headers (not request body)
- Wallet-link create binds record to authenticated `tenant_id` + `user_id`
- Unlink verifies record ownership before mutation — no cross-user state change possible
- Persistent store is user-isolated at query time (`list_links_for_user` filters by tenant_id + user_id)

---

## 3. Files Created / Modified (Full Repo-Root Paths)

### Created
- `projects/polymarket/polyquantbot/tests/test_phase8_5_persistent_wallet_link_20260419.py`
- `projects/polymarket/polyquantbot/reports/forge/phase8-5_01_persistent-wallet-link-foundation.md` (this file)

### Modified
- `projects/polymarket/polyquantbot/server/storage/wallet_link_store.py` (abstract base + PersistentWalletLinkStore)
- `projects/polymarket/polyquantbot/server/services/wallet_link_service.py` (unlink_link + error classes)
- `projects/polymarket/polyquantbot/server/api/client_auth_routes.py` (PATCH unlink route)
- `projects/polymarket/polyquantbot/server/main.py` (PersistentWalletLinkStore wiring + env var)
- `PROJECT_STATE.md` (Part A truth sync + Part B state)
- `ROADMAP.md` (Phase 8.4 close + Phase 8.5 checklist)

---

## 4. What Is Working

**Persistent Storage (unit-tested directly on PersistentWalletLinkStore):**
- `put_link` writes to disk and reads back correctly after fresh init
- `_load_from_disk()` recovers all records on a second store instance (simulated restart)
- `set_link_status` updates status and persists — reloaded store shows updated state
- `set_link_status` raises `WalletLinkStorageError` for unknown link_id
- `list_links_for_user` returns only matching user's records — cross-user isolation at storage level

**Restart-Safe Readback (integration-tested via HTTP):**
- Wallet-link created in app instance 1 — present in app instance 2 with same storage path
- Multiple users' wallet-links survive restart with correct cross-user isolation
- Unlinked status persists across simulated restart

**Unlink Lifecycle (integration-tested via HTTP):**
- `PATCH /auth/wallet-links/{link_id}/unlink` sets status to `unlinked` and returns updated record
- Unlink by non-owner returns 403 — ownership enforcement holds
- Unlink for unknown link_id returns 404
- Unauthenticated unlink attempt returns 403 (scope dependency enforced)

**Regression (Phase 8.4 + 8.1 tests):**
- All 20 prior tests pass — 0 regressions

**Full pytest evidence (33/33 pass):**
```
platform linux -- Python 3.11.15, pytest-9.0.3, pluggy-1.6.0
rootdir: /home/user/walker-ai-team
configfile: pytest.ini
plugins: anyio-4.13.0

Phase 8.5 tests (13/13):
test_persistent_store_put_and_get_roundtrip                    PASSED
test_persistent_store_load_from_disk_on_init                   PASSED
test_persistent_store_set_link_status                          PASSED
test_persistent_store_set_link_status_not_found_raises         PASSED
test_persistent_store_list_for_user_scoped                     PASSED
test_wallet_link_persists_across_app_restart                   PASSED
test_multiple_users_wallet_links_survive_restart               PASSED
test_unlink_wallet_link_sets_status_unlinked                   PASSED
test_unlink_status_persists_after_restart                      PASSED
test_unlink_not_found_returns_404                              PASSED
test_unlink_cross_user_denied_returns_403                      PASSED
test_unlink_requires_authenticated_session                     PASSED
test_persistent_cross_user_isolation_via_http                  PASSED

Phase 8.4 regression (12/12):
test_handoff_validates_known_telegram_client                   PASSED
test_handoff_validates_known_web_client                        PASSED
test_handoff_rejects_unsupported_client_type                   PASSED
test_handoff_rejects_empty_claim                               PASSED
test_handoff_rejects_empty_scope                               PASSED
test_client_handoff_issues_session_for_known_user              PASSED
test_client_handoff_rejects_unknown_user                       PASSED
test_client_handoff_rejects_unsupported_client_type_via_route  PASSED
test_wallet_link_create_and_read_for_authenticated_user        PASSED
test_wallet_link_requires_authenticated_session                PASSED
test_wallet_link_cross_user_isolation                          PASSED
test_wallet_link_cross_tenant_session_denied                   PASSED

Phase 8.1 regression (8/8):
test_scope_resolution_rejects_empty_tenant                     PASSED
test_scope_ownership_detects_mismatch                          PASSED
test_multi_user_routes_enforce_wallet_scope                    PASSED
test_scope_dependency_rejects_missing_session                  PASSED
test_scope_dependency_derives_authenticated_scope              PASSED
test_persisted_session_readback_and_restart_safe_scope         PASSED
test_revoked_session_is_rejected                               PASSED
test_expired_session_is_rejected                               PASSED

33 passed, 1 warning in 4.42s
```

---

## 5. Known Issues

- `WalletLinkStore` (abstract base) has `raise NotImplementedError` methods — not an ABC-enforced contract; this is intentional to preserve the SessionStore pattern and avoid over-engineering at this foundation stage
- `client_identity_claim` remains structurally validated only — no cryptographic verification (explicit deferred gate; consistent with Phase 8.4 FOUNDATION scope)
- `Unknown config option: asyncio_mode` warning in pytest is pre-existing hygiene backlog (carried from Phase 8.3, non-runtime)
- `InMemoryMultiUserStore` (Phase 8.1 user store) is still in-memory — persistent user store is a future lane

---

## 6. What Is Next

SENTINEL validation required for Phase 8.5 before merge.

Source: `projects/polymarket/polyquantbot/reports/forge/phase8-5_01_persistent-wallet-link-foundation.md`
Tier: MAJOR

Validation Target:
- `PersistentWalletLinkStore` persistence contract (put/load/restart roundtrip)
- `set_link_status` lifecycle boundary (not-found error, status persistence)
- `unlink_link` ownership enforcement (cross-user denial, 403 path)
- Authenticated scope on all wallet-link routes (403 on missing session)
- Regression coverage on Phase 8.4 + 8.1 test suites

After SENTINEL validates and COMMANDER approves merge, the next public-readiness lanes are:
- Persistent multi-user store (user/account/wallet records beyond in-memory)
- Telegram bot handler thin integration (client-side handoff surface)
- RBAC / permission scope hardening (further production gate)

---

**Validation Tier:** MAJOR
**Claim Level:** FOUNDATION
**Validation Target:** persistent wallet-link storage boundary + minimal unlink lifecycle enforcement + authenticated ownership isolation
**Not in Scope:** full wallet lifecycle orchestration, delegated signing, exchange/on-chain rollout, full RBAC, OAuth, production token rotation, broad portfolio engine, full DB migration platform
**Suggested Next:** SENTINEL validation required before merge
