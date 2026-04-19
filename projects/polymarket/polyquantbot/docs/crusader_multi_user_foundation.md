# Crusader Multi-User Foundation (Lanes 8.1-8.2)

This document records the first backend implementation lanes for Crusader multi-user isolation foundations and the initial auth/session scope bridge.

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
  - wallet read route now derives scope from authenticated session context

## Scope and truth boundaries

These lanes introduce ownership and trusted scope derivation primitives only.

Included:
- identity and ownership mapping primitives
- tenant/user scope resolution
- user/account/wallet/user_settings schema + storage foundation
- thin service boundaries and minimal API surface for these entities
- minimal trusted session context + authenticated scope dependency

Not included:
- full Telegram auth/session UX
- full web auth flow
- OAuth rollout
- production token rotation platform
- full RBAC and notification system
- delegated wallet signing lifecycle
- database migration rollout

## Why this matters

The backend now has explicit per-user ownership boundaries and a truthful first auth/session bridge so future lanes can replace manual scope inputs with trusted runtime identity context without overclaiming full auth productization.
