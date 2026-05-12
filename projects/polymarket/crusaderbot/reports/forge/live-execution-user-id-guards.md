# Forge Report — live-execution-user-id-guards

- Branch: `WARP/live-execution-user-id-guards`
- Validation Tier: **MAJOR**
- Claim Level: **NARROW INTEGRATION**
- Project: `projects/polymarket/crusaderbot`
- Timestamp (Asia/Jakarta): **2026-05-13 06:01**

## Objective
Harden live execution persistence updates so position lifecycle UPDATE statements are user-scoped by both `id` and `user_id`.

## Scope
- `projects/polymarket/crusaderbot/domain/execution/live.py`
- `projects/polymarket/crusaderbot/tests/test_live_execution_rewire.py`
- State files and changelog updates in `projects/polymarket/crusaderbot/state/`

## Implementation
Added `user_id` guards to all scoped live close UPDATE paths:
1. atomic claim `open -> closing`
2. rollback `closing -> open` (config error path)
3. rollback `closing -> open` (submit exception path)
4. finalize `closing -> closed`

All four now require matching `id` and `user_id`.

## Validation Target
Verify live execution persistence updates positions only when both `position_id` and `user_id` match.

## Validation Evidence
- Added unit assertion coverage to verify guarded SQL predicates and bound arguments include `user_id` for claim/finalize paths in close flow.
- Existing rollback tests still verify status rollback behavior on failure.

## Not in Scope
- Enabling live trading
- Changing `ENABLE_LIVE_TRADING`
- Real CLOB activation
- Wallet/key handling changes
- Capital/risk sizing changes
- Strategy changes
- Schema migrations

## Risk
- Runtime behavior impact is limited to authorization/ownership guard on existing UPDATE statements.
- No changes to strategy, order routing, pricing, or guard flags.
