# WARP•FORGE Report — realtime-deposit-withdraw-engine

Branch: warp/implement-realtime-deposit-and-withdraw-engine (exact PR #1781 head)
Project: CrusaderBot
Project Path: projects/polymarket/crusaderbot
Issue: #1780
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Status: R00T-FINISHED — WARP•R00T finishing pass complete; WARP•R00T took final gate responsibility (PR #1781, self-merge on CI green)
Last Updated: 2026-06-12 19:05

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
- Guard-off mode DEFERS: the realtime trigger performs NO sweep and does NOT mark rows swept — deposits stay `swept=FALSE` / lifecycle `available`, fully eligible for the 03:00 cron and for the on-chain path once guards are armed (WARP•R00T fix; the original logical `swept=TRUE` flip could have burned on-chain sweep eligibility for real deposits).
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
- `pytest projects/polymarket/crusaderbot/tests/test_deposit_e2e.py projects/polymarket/crusaderbot/tests/test_deposit_reorg.py projects/polymarket/crusaderbot/tests/test_sweep_deposits.py projects/polymarket/crusaderbot/tests/test_wallet_withdraw_flow.py projects/polymarket/crusaderbot/tests/test_watch_deposits_rescue.py -q` — 51 passed (post-R00T finishing pass).
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

## WARP•R00T Finishing Pass (PR #1781)

WARP•R00T performed the senior finishing/hardening pass after the FORGE build
and is taking final gate responsibility for this MAJOR lane (full-bypass
authority; WARP•SENTINEL did not run and is not claimed).

Fixes applied on top of the FORGE build:

1. CMD blocker 3 — guard-off realtime sweep semantics. `scheduler._sweep_confirmed_deposits_for_users()` no longer marks `swept=TRUE` when `EXECUTION_PATH_VALIDATED`/`SWEEP_ONCHAIN_ENABLED` are off; it logs + audits a `deposit_sweep_realtime_deferred` event and leaves rows sweep-eligible. A deposit may only become `swept` when funds actually moved (on-chain path) or via the explicitly-logical nightly paper reconciliation.
2. Lifecycle truth-bleed — `scheduler._sweep_deposits_onchain()` transient failure now annotates `manual_review` + `sweep_error` instead of `failed` (`failed` is reserved for reverted deposits per the migration 095 backfill; the deposit stays credited and sweep-retryable).
3. CI red — `tests/test_deposit_reorg.py` mocks updated for the new 4-tuple confirm shape and the 2-arg lifecycle revert SQL; the 3 failing tests now pass and additionally pin reverted-deposit lifecycle `failed`.
4. Operator/user truth — deposit confirmation notification no longer claims "sweep queued/complete" unconditionally; it states custody sweep follows when enabled.
5. Test hardening — 3 new unit tests pin `_sweep_confirmed_deposits_for_users` defer (no DB write, audit event), guard-on dispatch (deduped user_ids + reason to `_sweep_deposits_onchain`), and empty-target no-op.
6. Repo-truth sync — exact PR head branch `warp/implement-realtime-deposit-and-withdraw-engine` written into report/state/changelog; PROJECT_STATE wording corrected from premature COMPLETED-with-pending-gate to R00T-final-gate truth; PR body aligned with actual validation evidence.

Follow-ups (non-blocking, separate lanes if wanted):
- Completed withdrawals render lifecycle `swept` in user history; a small display mapping (`swept` -> `completed`) would read better for end users.
- The nightly logical cron still flips ALL unswept rows `swept=TRUE` in guard-off mode (pre-existing, documented paper-mode reconciliation). If real deposits will sit in guard-off mode for long, consider restricting the logical cron the same way.

## Next Gate

WARP•R00T is taking final gate responsibility for this MAJOR lane (AGENTS.md
WARP•R00T full-bypass merge authority): merge on CI green of the final head.
No WARP•SENTINEL verdict exists for this PR and none is claimed.
