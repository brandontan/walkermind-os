# Phase 1 Platform Foundation (Read-Only Bridge)

This package introduces **foundation-only** contracts and service skeletons for future
multi-user migration without changing current legacy trading behavior.

## Purpose

- Define typed contracts for account, wallet/auth, permission, and execution context.
- Resolve platform context from legacy session inputs.
- Attach context in read-only mode so legacy runtime can observe metadata safely.

## Read-only bridge behavior

- Controlled by env flags:
  - `ENABLE_PLATFORM_CONTEXT_BRIDGE` (default: `false`)
  - `PLATFORM_CONTEXT_STRICT_MODE` (default: `false`)
- When bridge is disabled, legacy flow is unchanged.
- When enabled and resolution succeeds, context metadata is attached for diagnostics.
- When enabled and resolution fails:
  - non-strict mode: legacy flow continues unchanged (fallback)
  - strict mode: flow is blocked intentionally for development validation

## Future extension points

- Replace placeholder account/wallet/permission lookup with persistent stores.
- Expand context resolver for multi-user runtime and execution queues.
- Add authenticated wallet/session wiring in later phases.

## Explicit non-goal for Phase 1

This foundation does **not** provide live wallet/auth execution support and does not
alter strategy, risk, or order submission behavior.
