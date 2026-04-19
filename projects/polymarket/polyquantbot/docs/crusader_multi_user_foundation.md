# Crusader Multi-User Foundation (Lane 8.1)

This document records the first backend implementation lane for Crusader multi-user isolation foundations.

## What exists now

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
- `projects/polymarket/polyquantbot/server/api/multi_user_foundation_routes.py`
  - minimal testable backend routes under `/foundation`

## Scope and truth boundaries

This lane introduces ownership and tenant scope primitives only.

Included:
- identity and ownership mapping primitives
- tenant/user scope resolution
- user/account/wallet/user_settings schema + storage foundation
- thin service boundaries and minimal API surface for these entities

Not included:
- full auth/session UX
- production session hardening
- full wallet lifecycle orchestration
- delegated signing rollout
- full RBAC and notification system

## Why this matters

The backend now has explicit per-user ownership boundaries that future auth/session, wallet linking, and per-user portfolio isolation lanes can build on without pretending full product completeness.
