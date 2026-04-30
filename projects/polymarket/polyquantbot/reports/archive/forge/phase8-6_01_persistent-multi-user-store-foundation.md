# Phase 8.5 + 8.6 — Post-Merge Truth Sync + Persistent Multi-User Store Foundation

**Date:** 2026-04-19 12:12
**Branch:** claude/phase-8-5-8-6-persistent-store-25UO0
**Validation Tier:** MAJOR
**Claim Level:** FOUNDATION
**Validation Target:** persistent multi-user storage boundary (user/account/wallet) + restart-safe ownership chain + cross-user isolation + service abstraction over MultiUserStore
**Not in Scope:** full database rollout, full portfolio engine, exchange execution changes, on-chain settlement changes, RBAC, OAuth, delegated signing lifecycle, full wallet lifecycle orchestration
**Suggested Next:** SENTINEL validation required before merge

---

## 1. What Was Built

### Part A — Phase 8.5 Post-Merge Truth Sync

- `PROJECT_STATE.md` updated: Phase 8.5 moved from IN PROGRESS (SENTINEL pending) to COMPLETED (merged); Phase 8.6 moved from NOT STARTED to IN PROGRESS; NEXT PRIORITY updated to SENTINEL for Phase 8.6.
- `ROADMAP.md` updated: Phase 8.5 checklist status changed from `🚧 In Progress — SENTINEL validation required before merge` to `✅ Done (merged)`; Phase 8.6 checklist section added.
- Truthful references preserved:
  - `projects/polymarket/polyquantbot/reports/forge/phase8-5_01_persistent-wallet-link-foundation.md`
  - `projects/polymarket/polyquantbot/reports/forge/phase8-5_02_pytest-evidence-pass.md`
  - `projects/polymarket/polyquantbot/reports/sentinel/phase8-5_01_wallet-link-persistence-validation.md`

### Part B — Phase 8.6 Persistent Multi-User Store Foundation

**1. Abstract Multi-User Storage Boundary (`server/storage/multi_user_store.py`)**

New file establishing the abstract store contract and persistent implementation:

- `MultiUserStoreError` — typed exception for storage read/write failures
- `MultiUserStore` — abstract base class with:
  - `put_user`, `get_user`
  - `put_user_settings`, `get_user_settings_for_user`
  - `put_account`, `get_account`, `list_accounts_for_user`
  - `put_wallet`, `get_wallet`, `list_wallets_for_account`
- `PersistentMultiUserStore(MultiUserStore)` — local-file JSON storage with:
  - Deterministic atomic overwrite via temp-file replace (same pattern as PersistentSessionStore and PersistentWalletLinkStore)
  - `_load_from_disk()` on init — restart-safe record recovery for all four entity types
  - `_persist_to_disk()` on every write — format version 1, four entity arrays, sorted by primary key
  - Configurable path via `CRUSADER_MULTI_USER_STORAGE_PATH` env var

**2. In-Memory Store Compatibility (`server/storage/in_memory_store.py`)**

- `InMemoryMultiUserStore` now extends `MultiUserStore` abstract base
- Added `list_accounts_for_user` and `list_wallets_for_account` to match the full interface
- Added `get_user_settings_for_user` for settings lookup by user_id
- Zero behavioral change — all existing tests continue to pass

**3. Service Abstraction (`server/services/`)**

Switched type hints from `InMemoryMultiUserStore` to `MultiUserStore` in all four services:
- `UserService.__init__`
- `AccountService.__init__`
- `WalletService.__init__`
- `AuthSessionService.__init__`

All service method calls (`get_user`, `put_user`, `get_account`, `put_account`, `get_wallet`, `put_wallet`) are in the `MultiUserStore` interface — no behavioral change.

**4. App Wiring (`server/main.py`)**

- Replaced `InMemoryMultiUserStore()` with `PersistentMultiUserStore(storage_path=multi_user_storage_path)`
- Added `CRUSADER_MULTI_USER_STORAGE_PATH` env var (default: `/tmp/crusaderbot/runtime/multi_user.json`)
- Added `multi_user_storage_path` to `app.state` for observability
- Phase log updated to `8.6`

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
  -> PersistentMultiUserStore.get_user()   <- restart-safe user lookup
  -> PersistentSessionStore.put_session()  <- restart-safe session write
        |
        v
Authenticated client
        |
        v
POST /foundation/users      -> PersistentMultiUserStore.put_user + put_user_settings -> disk
POST /foundation/accounts   -> PersistentMultiUserStore.put_account -> disk
POST /foundation/wallets    -> PersistentMultiUserStore.put_wallet  -> disk
GET  /foundation/wallets/id -> PersistentMultiUserStore.get_wallet  + ownership check
        |
        v
PersistentMultiUserStore (multi_user.json) <- restart-safe
  format: { "version": 1, "users": [...], "user_settings": [...], "accounts": [...], "wallets": [...] }
  _load_from_disk()  on init (recovers all four entity types)
  _persist_to_disk() on every mutation (atomic temp-file replace)

PersistentSessionStore   (sessions.json)      <- restart-safe (Phase 8.3)
PersistentWalletLinkStore (wallet_links.json) <- restart-safe (Phase 8.5)
```

Ownership chain is unbroken:
- `create_user` binds user to `tenant_id`
- `create_account` validates `user.tenant_id == account.tenant_id`
- `create_wallet` validates `account.tenant_id + account.user_id == wallet.tenant_id + wallet.user_id`
- `get_wallet_for_scope` enforces ownership before returning data
- All records survive restart — ownership chain verifiable from disk after restart

---

## 3. Files Created / Modified (Full Repo-Root Paths)

### Created
- `projects/polymarket/polyquantbot/server/storage/multi_user_store.py`
- `projects/polymarket/polyquantbot/tests/test_phase8_6_persistent_multi_user_store_20260419.py`
- `projects/polymarket/polyquantbot/reports/forge/phase8-6_01_persistent-multi-user-store-foundation.md` (this file)

### Modified
- `projects/polymarket/polyquantbot/server/storage/in_memory_store.py` (extends MultiUserStore + list methods)
- `projects/polymarket/polyquantbot/server/services/user_service.py` (MultiUserStore type)
- `projects/polymarket/polyquantbot/server/services/account_service.py` (MultiUserStore type)
- `projects/polymarket/polyquantbot/server/services/wallet_service.py` (MultiUserStore type)
- `projects/polymarket/polyquantbot/server/services/auth_session_service.py` (MultiUserStore type)
- `projects/polymarket/polyquantbot/server/main.py` (PersistentMultiUserStore wiring + env var + phase 8.6)
- `PROJECT_STATE.md` (Part A truth sync + Part B Phase 8.6 state)
- `ROADMAP.md` (Phase 8.5 close + Phase 8.6 checklist)

---

## 4. What Is Working

**Persistent Storage (unit-tested directly on PersistentMultiUserStore):**
- `put_user` / `put_account` / `put_wallet` write to disk and read back correctly after fresh init
- `_load_from_disk()` recovers all four entity types on a second store instance (simulated restart)
- `get_user_settings_for_user` returns correct settings by user_id after reload
- `list_accounts_for_user` returns only the requesting user's accounts (cross-user isolation at storage level)
- `list_wallets_for_account` returns only wallets for the given account

**Restart-Safe Readback (integration-tested via HTTP):**
- User created in app instance 1 — session can be issued for that user in app instance 2
- Wallet created in app instance 1 — `GET /foundation/wallets/{id}` returns correct data in app instance 2
- Ownership chain (user → account → wallet) remains intact and verifiable after restart

**Cross-User Isolation (integration-tested via HTTP):**
- User B cannot read User A's wallet after restart — `GET /foundation/wallets/{wallet_a_id}` returns 403 when using User B's session
- `InMemoryMultiUserStore` regression: cross-user isolation holds in-memory as before

**Regression (Phase 8.5 + 8.4 + 8.1 tests):**
- 13/13 Phase 8.5 tests pass — persistent wallet-link store unaffected
- 12/12 Phase 8.4 tests pass — client auth handoff and wallet-link routes unaffected
- 8/8 Phase 8.1 tests pass — scope/ownership foundation unaffected

**Full pytest evidence (46/46 pass):**
```
platform linux -- Python 3.11.15, pytest-9.0.2, pluggy-1.6.0
rootdir: /home/user/walker-ai-team
configfile: pytest.ini
plugins: anyio-4.13.0

Phase 8.6 tests (13/13):
test_persistent_store_user_put_and_get_roundtrip              PASSED
test_persistent_store_account_put_and_get_roundtrip           PASSED
test_persistent_store_wallet_put_and_get_roundtrip            PASSED
test_persistent_store_load_from_disk_on_init                  PASSED
test_persistent_store_user_settings_roundtrip                 PASSED
test_persistent_store_list_accounts_for_user                  PASSED
test_persistent_store_list_wallets_for_account                PASSED
test_persisted_user_readback                                  PASSED
test_persisted_account_readback                               PASSED
test_persisted_wallet_readback                                PASSED
test_restart_safe_ownership_chain_intact                      PASSED
test_cross_user_isolation_after_restart                       PASSED
test_cross_user_isolation_regression                          PASSED

Phase 8.5 regression (13/13): all PASSED
Phase 8.4 regression (12/12): all PASSED
Phase 8.1 regression (8/8):   all PASSED

46 passed, 1 warning in 5.65s
```

---

## 5. Known Issues

- `MultiUserStore` uses `raise NotImplementedError` methods rather than ABC-enforced contract — intentional to preserve the SessionStore / WalletLinkStore pattern at this foundation stage
- `client_identity_claim` structural validation only — no cryptographic verification (explicit deferred gate, consistent with Phase 8.4 FOUNDATION scope)
- `Unknown config option: asyncio_mode` warning in pytest is pre-existing hygiene backlog (carried forward, non-runtime)
- `PersistentMultiUserStore` performs a full disk write on every mutation — acceptable for foundation scale; batched writes are a future optimization lane

---

## 6. What Is Next

SENTINEL validation required for Phase 8.6 before merge.

Source: `projects/polymarket/polyquantbot/reports/forge/phase8-6_01_persistent-multi-user-store-foundation.md`
Tier: MAJOR

Validation Target:
- `PersistentMultiUserStore` persistence contract (put/load/restart roundtrip for user/account/wallet)
- `_load_from_disk()` recovery of all four entity types
- Ownership chain verification after simulated restart
- Cross-user isolation after restart
- Service abstraction: all services operate correctly over `MultiUserStore` interface
- Regression coverage for Phase 8.5 / 8.4 / 8.1 test suites

After SENTINEL validates and COMMANDER approves merge, the next public-readiness lanes are:
- Telegram bot handler thin integration (client-side handoff surface)
- RBAC / permission scope hardening (production gate)
- User settings retrieval route (expose GET /foundation/users/{id}/settings)

---

**Validation Tier:** MAJOR
**Claim Level:** FOUNDATION
**Validation Target:** persistent multi-user storage boundary + restart-safe ownership chain + cross-user isolation + service-level abstraction over MultiUserStore interface
**Not in Scope:** full database rollout, portfolio engine, exchange execution changes, on-chain settlement changes, RBAC, OAuth, delegated signing lifecycle, full wallet lifecycle orchestration
**Suggested Next:** SENTINEL validation required before merge
