# Crusader Multi-User Foundation (Lanes 8.1-8.3)

This document records the first backend implementation lanes for Crusader multi-user isolation foundations and the auth/session backbone progression.

## What exists now

### Lane 8.1 — Ownership primitives

- `projects/polymarket/polyquantbot/server/core/scope.py`
  - scope resolution helper (`tenant_id` + `user_id` required)
  - ownership check and ownership enforcement helpers
- `projects/polymarket/polyquantbot/server/schemas/multi_user.py`
  - schema foundation for `user`, `account`, `wallet`, and `user_settings`
- `projects/polymarket/polyquantbot/server/storage/in_memory_store.py`
  - minimal scoped storage boundary for foundation entities
- `projects/polymarket/polyquantbot/server/services/`
  - `user_service.py`
  - `account_service.py`
  - `wallet_service.py`

### Lane 8.2 — Auth/session foundation

- `projects/polymarket/polyquantbot/server/schemas/auth_session.py`
  - auth identity context
  - session context
  - trusted header contract
  - authenticated scope result
- `projects/polymarket/polyquantbot/server/core/auth_session.py`
  - trusted scope derivation from identity headers + active session
- `projects/polymarket/polyquantbot/server/services/auth_session_service.py`
  - minimal session issuance for existing scoped users
  - authenticated scope resolution with session validation
- `projects/polymarket/polyquantbot/server/api/auth_session_dependencies.py`
  - FastAPI dependency for trusted authenticated scope injection
- `projects/polymarket/polyquantbot/server/api/multi_user_foundation_routes.py`
  - `/foundation/sessions` minimal session creation route
  - `/foundation/auth/scope` trusted-scope inspection route
  - wallet read route derives scope from authenticated session context

### Lane 8.3 — Persistent session foundation

- `projects/polymarket/polyquantbot/server/storage/session_store.py`
  - local-file persistent session storage boundary
  - deterministic JSON format (`version=1`) with restart-safe load and write
- `projects/polymarket/polyquantbot/server/main.py`
  - wires `PersistentSessionStore` using `CRUSADER_SESSION_STORAGE_PATH`
  - default path: `/tmp/crusaderbot/runtime/foundation_sessions.json`
- `projects/polymarket/polyquantbot/server/services/auth_session_service.py`
  - session persistence moved from in-memory dict into persistent session storage boundary
  - status transition support (`active`, `revoked`) via storage update
- `projects/polymarket/polyquantbot/server/api/multi_user_foundation_routes.py`
  - adds `/foundation/sessions/{session_id}/revoke` minimal invalidation endpoint

## Scope and truth boundaries

These lanes introduce ownership boundaries and a persistent auth/session backbone for foundation routes only.

Included:
- identity and ownership mapping primitives
- tenant/user scope resolution
- user/account/wallet/user_settings schema + storage foundation
- thin service boundaries and minimal API surface for these entities
- trusted session context + authenticated scope dependency
- restart-safe persistence for issued session records
- minimal session revocation lifecycle support

Not included:
- full Telegram auth/session UX
- full web auth flow
- OAuth rollout
- production token rotation platform
- full RBAC and notification system
- delegated wallet signing lifecycle
- database migration rollout
- broad wallet lifecycle rollout

## Why this matters

The backend now keeps session identity continuity across process restarts for the auth/session foundation lane, which is a real bridge toward public-ready runtime surfaces.

This is still not full production auth. Current identity handoff remains trusted-header foundation flow for controlled backend surfaces while broader client auth and wallet-linking lanes remain explicitly pending.
