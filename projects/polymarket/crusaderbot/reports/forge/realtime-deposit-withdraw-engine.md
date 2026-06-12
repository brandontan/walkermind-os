# WARP•FORGE Report — realtime-deposit-withdraw-engine

Branch: WARP/realtime-deposit-withdraw-engine
Project: CrusaderBot
Project Path: projects/polymarket/crusaderbot
Issue: #1780
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Status: BUILT — PR ready for WARP•SENTINEL validation
Last Updated: 2026-06-12 17:30

## Scope

Implemented the near-realtime deposit/withdraw lifecycle requested by GitHub issue #1780 for the existing CrusaderBot custody paths.

In scope:
- Near-realtime USDC.e deposit confirmation lifecycle.
- Immediate sweep trigger after confirmed deposits.
- Cron sweep preserved as fallback/reconciliation.
- Formal lifecycle state vocabulary for deposit/withdraw accounting.
- Withdrawal available-balance lock, guarded submit, confirmation metadata, and failure unlock/manual-review semantics.
- Telegram/admin status wording for deposit and withdraw lifecycle truth.
- Idempotency tests for deposit crediting and withdrawal transfer retry behavior.

Not in scope and not changed:
- No automatic live-trading enablement.
- No strategy rewrite.
- No risk model redesign.
- No real fund movement in tests.
- No bypass of ENABLE_LIVE_TRADING / EXECUTION_PATH_VALIDATED / USE_REAL_CLOB owner gates.
- No change to user risk/concurrency authority.

## Implementation Summary

### Deposit lifecycle and immediate sweep

- Added migration `projects/polymarket/crusaderbot/migrations/095_realtime_deposit_withdraw_lifecycle.sql`.
- Added `deposits.lifecycle_state`, `deposits.sweep_tx_hash`, and `deposits.sweep_error`.
- Added formal lifecycle constants in `wallet/ledger.py`:
  - detected
  - confirming
  - available
  - reserved_for_order
  - in_position
  - withdraw_pending
  - sweeping
  - swept
  - failed
  - manual_review
- `scheduler.watch_deposits()` now separates:
  1. detect inbound transfer -> pending / confirming
  2. wait for confirmation depth
  3. promote to confirmed / available and credit ledger once
  4. trigger immediate per-user sweep attempt
- `_sweep_confirmed_deposits_for_users()` targets only users confirmed during that watcher tick.
- On-chain sweep remains behind existing `EXECUTION_PATH_VALIDATED + SWEEP_ONCHAIN_ENABLED` guards.
- Guard-off mode performs immediate logical reconciliation (`swept=TRUE`, lifecycle `swept`) instead of waiting for 03:00 cron.
- The 03:00 `sweep_deposits()` job remains intact as fallback/reconciliation.
- Sweep failures are isolated from deposit confirmation; confirmed deposits stay credited and cron fallback remains available.

### Withdrawal lifecycle

- Added `withdrawals.lifecycle_state`, `withdrawals.submitted_at`, and `withdrawals.confirmed_at`.
- `create_withdrawal_request()` now writes lifecycle `withdraw_pending` as the available-balance lock state.
- The existing `FOR UPDATE` wallet balance check and debit remain the concurrency/double-withdraw guard.
- `_attempt_onchain_transfer()` writes lifecycle `confirming` when submitted and lifecycle `swept` when completed/confirmed.
- Preflight failures remain refund-safe: withdrawal is failed and ledger is credited back.
- Ambiguous post-broadcast failures now use lifecycle `manual_review` while preserving the existing no-auto-refund rule.
- Existing tx-hash idempotency remains: rows with a tx hash are never resent.

### Telegram/admin status truth

- Deposit confirmation notification now reports the lifecycle path: confirming -> available -> sweep queued/complete.
- Deposit instructions now tell users confirmed deposits are credited and swept immediately when custody sweep is enabled.
- Withdrawal confirmation/submission copy now states funds lock immediately before payout submission.
- Withdrawal history and admin withdrawal cards now render lifecycle state.

## Safety Notes

- Live movement remains impossible unless existing live/custody flags are explicitly enabled by operators.
- No code flips `USE_REAL_CLOB`, `EXECUTION_PATH_VALIDATED`, `ENABLE_LIVE_TRADING`, or `SWEEP_ONCHAIN_ENABLED`.
- No secrets or secret values were added.
- Tests use mocked chain/RPC/custody behavior only; no real fund movement.
- Immediate sweep failure does not roll back or hide a confirmed deposit credit; it is logged and left for cron/operator reconciliation.

## Validation Performed

- `python3 -m pip install -e projects/polymarket/crusaderbot` — installed project dependencies required for local tests.
- `python3 -m py_compile projects/polymarket/crusaderbot/scheduler.py projects/polymarket/crusaderbot/wallet/ledger.py projects/polymarket/crusaderbot/wallet/withdrawals.py projects/polymarket/crusaderbot/bot/messages.py projects/polymarket/crusaderbot/tests/test_deposit_e2e.py` — passed, with pre-existing SyntaxWarnings in `bot/messages.py` invalid Markdown escape strings.
- `python3 -m ruff check projects/polymarket/crusaderbot/scheduler.py projects/polymarket/crusaderbot/wallet/ledger.py projects/polymarket/crusaderbot/wallet/withdrawals.py projects/polymarket/crusaderbot/bot/messages.py projects/polymarket/crusaderbot/tests/test_deposit_e2e.py` — passed.
- `pytest projects/polymarket/crusaderbot/tests/test_deposit_e2e.py projects/polymarket/crusaderbot/tests/test_sweep_deposits.py projects/polymarket/crusaderbot/tests/test_wallet_withdraw_flow.py -q` — 37 passed.
- Touched-file mojibake scan — passed.
- Touched-file secret-value scan — passed.

## Files Changed

- `projects/polymarket/crusaderbot/scheduler.py`
- `projects/polymarket/crusaderbot/wallet/ledger.py`
- `projects/polymarket/crusaderbot/wallet/withdrawals.py`
- `projects/polymarket/crusaderbot/bot/messages.py`
- `projects/polymarket/crusaderbot/tests/test_deposit_e2e.py`
- `projects/polymarket/crusaderbot/migrations/095_realtime_deposit_withdraw_lifecycle.sql`
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`
- `projects/polymarket/crusaderbot/reports/forge/realtime-deposit-withdraw-engine.md`

## Next Gate

WARP•SENTINEL required before merge because this is MAJOR custody/capital movement work.
