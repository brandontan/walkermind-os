# FORGE-X Report — wallet-lifecycle-foundation

**Branch:** NWAP/wallet-lifecycle-foundation
**Date:** 2026-04-25
**Validation Tier:** MAJOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Sections 25–30 of WORKTODO.md — Wallet Lifecycle Foundation
**Not in Scope:** Portfolio management, multi-wallet orchestration, live Polymarket signing, on-chain settlement, production RBAC

---

## 1. What Was Built

Priority 4 Wallet Lifecycle Foundation — a complete FSM-based lifecycle layer for user-owned wallets, covering sections 25–30 of WORKTODO.md.

**State machine (Section 25):**
```
unlinked → linked → active → deactivated
active/linked → blocked   (admin only)
blocked → linked           (admin only — unblock)
deactivated → linked       (re-link / recovery)
```

**Layer summary:**

| Layer | File | Coverage |
|---|---|---|
| Domain schema + FSM guards | `server/schemas/wallet_lifecycle.py` | Section 25 |
| PostgreSQL storage + audit log | `server/storage/wallet_lifecycle_store.py` | Section 27 |
| DB DDL (idempotent) | `infra/db/database.py` | Section 27 |
| FSM service (all transitions) | `server/services/wallet_lifecycle_service.py` | Sections 26–28, 30 |
| Ownership boundary | `platform/wallet_auth/wallet_lifecycle_foundation.py` | Section 28 |
| Telegram status surface | `telegram/handlers/wallet.py` | Section 29 |
| Runtime wiring | `server/main.py` | All |
| E2E tests | `tests/test_priority4_wallet_lifecycle_e2e.py` | Sections 25–30 |

---

## 2. Current System Architecture

```
Telegram Bot
    └── handle_wallet_lifecycle_status()  (Section 29 — masked address display)
            │
            ▼
WalletLifecycleService  (Section 26–28)
    ├── create_wallet()        unlinked (new)
    ├── link_wallet()          unlinked → linked
    ├── activate_wallet()      linked → active
    ├── deactivate_wallet()    active/linked → deactivated
    ├── block_wallet()         active/linked → blocked   [admin]
    ├── unblock_wallet()       blocked → linked           [admin]
    └── recover_wallet()       deactivated → linked       (Section 30)

    Ownership guard at every transition:
        WalletOwnershipBoundary (platform/wallet_auth/wallet_lifecycle_foundation.py)
            ├── verify_ownership()  — tenant + user match required
            ├── require_admin()     — admin gate for block/unblock
            └── BLOCKED wallet hidden from non-admin

WalletLifecycleStore  (Section 27)
    ├── upsert_wallet()        — idempotent ON CONFLICT DO UPDATE
    ├── get_wallet()           — by wallet_id
    ├── get_wallet_by_address()— duplicate-address guard
    ├── list_wallets_for_user()— optionally filtered by status
    ├── append_audit()         — immutable audit log (ON CONFLICT DO NOTHING)
    └── list_audit_for_wallet()— full history read

PostgreSQL (DatabaseClient)
    ├── wallet_lifecycle       — current wallet state (PK: wallet_id)
    └── wallet_audit_log       — immutable history (PK: log_id)
```

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/polyquantbot/server/schemas/wallet_lifecycle.py`
- `projects/polymarket/polyquantbot/server/storage/wallet_lifecycle_store.py`
- `projects/polymarket/polyquantbot/server/services/wallet_lifecycle_service.py`
- `projects/polymarket/polyquantbot/tests/test_priority4_wallet_lifecycle_e2e.py`
- `projects/polymarket/polyquantbot/reports/forge/wallet-lifecycle-foundation.md` (this file)

**Modified:**
- `projects/polymarket/polyquantbot/infra/db/database.py` — `_DDL_WALLET_LIFECYCLE`, `_DDL_WALLET_AUDIT_LOG`, both called in `_apply_schema()`
- `projects/polymarket/polyquantbot/platform/wallet_auth/wallet_lifecycle_foundation.py` — `WalletOwnershipBoundary` + `WalletOwnershipPolicy` + `WalletOwnershipResult` appended (P4 section)
- `projects/polymarket/polyquantbot/telegram/handlers/wallet.py` — `_wallet_lifecycle_service` injector, `set_wallet_lifecycle_service()`, `handle_wallet_lifecycle_status()`
- `projects/polymarket/polyquantbot/server/main.py` — lifecycle store + service wired in lifespan post-DB-start; imports added

---

## 4. What Is Working

- FSM transition guards: 8 valid transitions, 3 admin-only, invalid transitions rejected
- `WalletLifecycleService`: create, link, activate, deactivate, block, unblock, recover — all with ownership guard + audit trail on every state change
- Duplicate address guard on wallet creation
- Ownership enforcement: cross-user access returns `privilege_error` without leaking wallet data
- `WalletOwnershipBoundary`: ownership check, admin requirement, BLOCKED wallet hidden from non-admin
- Telegram status surface: masked address display (first 6 + last 4 chars), FSM status icon per status, graceful empty/error states
- PostgreSQL DDL: `wallet_lifecycle` + `wallet_audit_log` tables created idempotently on `DatabaseClient.connect()`
- Lifecycle service wired in server lifespan after DB connects
- **Tests: 25/25 passing** (WL-01..WL-25, sections 25–30)

---

## 5. Known Issues

- `handle_wallet_lifecycle_status()` is not yet wired to a Telegram command (`/wallet` or `/wallet_status`) — the function exists and is tested but has no command routing entry in `telegram/command_handler.py`. Routing is deferred to the next lane or COMMANDER decision.
- Persistence tests (WL-12..WL-14) mock the store — live DB integration requires a running PostgreSQL instance (covered in SENTINEL gate).
- No API routes for wallet lifecycle management yet — service is available on `app.state.wallet_lifecycle_service` for future routing.
- `WalletLifecycleService` does not yet integrate with the Phase 6.5 `WalletStateStorageBoundary` (trading-wallet state storage) — that integration is scoped to Priority 5+ when portfolio management begins.

---

## 6. What Is Next

**Immediate (SENTINEL gate):**
- SENTINEL MAJOR validation required before P4 can be marked done and P5 opens
- Source: `projects/polymarket/polyquantbot/reports/forge/wallet-lifecycle-foundation.md`
- Tier: MAJOR

**After SENTINEL approval:**
- Wire `/wallet_status` Telegram command in `telegram/command_handler.py`
- Build Priority 5: Portfolio Management Logic (sections 31–36)
- Branch: `NWAP/portfolio-management` (COMMANDER to declare)

---

## Metadata

- **Validation Tier:** MAJOR
- **Claim Level:** NARROW INTEGRATION
- **Validation Target:** Sections 25–30 — Wallet Lifecycle Foundation (FSM, persistence, auth boundary, Telegram surface, recovery)
- **Not in Scope:** Portfolio management, multi-wallet orchestration, live Polymarket signing, production RBAC, Telegram command routing for `/wallet_status`
- **Suggested Next Step:** SENTINEL MAJOR validation sweep
