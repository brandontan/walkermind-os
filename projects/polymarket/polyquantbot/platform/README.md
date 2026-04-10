# Phase 2 Platform Foundation (Persistence + Wallet/Auth Skeleton)

This package extends the Phase 1 read-only bridge with **foundation-level persistence and auth skeleton contracts** for multi-user architecture.

## What is included in Phase 2 foundation

- Persistent repository contracts and dev-safe local JSON backend under:
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/storage/`
- Persistent records:
  - `UserAccountRecord`
  - `WalletBindingRecord`
  - `PermissionProfileRecord`
  - `StrategySubscriptionRecord`
  - `ExecutionContextRecord`
  - `AuditEventRecord`
- Service wiring upgrades:
  - `AccountService.resolve_user_account` is read-only; `ensure_user_account` performs explicit persistence when needed.
  - `WalletAuthService.resolve_wallet_binding` is read-only; `ensure_wallet_binding` performs explicit persistence when needed.
  - `PermissionService.resolve_permission_profile` is read-only; `ensure_permission_profile` performs explicit persistence when needed.
  - `ContextResolver` is pure and read-only: it composes `PlatformContextEnvelope` only and performs no persistence/audit writes.
- Strategy subscription foundation:
  - enable/disable strategy IDs per user via repository-backed service.
- Legacy bridge remains feature-flagged with strict/non-strict fallback continuity; resolver path remains read-only.

## Storage/backend configuration

- `PLATFORM_STORAGE_BACKEND`
  - `none` (default) keeps legacy-safe behavior with no persistence.
  - `json` enables dev-safe local JSON persistence.
  - `sqlite` currently maps to the same local skeleton backend (foundation placeholder).
- `PLATFORM_STORAGE_PATH`
  - local file path for persistent dev data.
- `PLATFORM_AUTH_PROVIDER`
  - `polymarket` or `skeleton` resolves to non-live auth provider skeleton.

Existing bridge controls are unchanged:
- `ENABLE_PLATFORM_CONTEXT_BRIDGE` (default: `false`)
- `PLATFORM_CONTEXT_STRICT_MODE` (default: `false`)

## Auth skeleton lifecycle (non-live)

Auth contracts are scaffold-only and make **no live network calls**:

- `bootstrap_l1_context`
- `derive_or_load_l2_context`
- `validate_auth_state`
- `normalize_funder_address`

All methods currently return deterministic placeholder values for local/dev testing.

## Explicit non-goals (deferred)

- Live Polymarket order placement
- Production L1 signing
- Production L2 credential issuance
- Execution engine authority changes
- Strategy logic or risk logic mutation
- Queue workers, websocket runtime subscriptions, reconciliation jobs
- Public API/UI clients
- Production secrets vault wiring
