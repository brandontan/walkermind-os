# WARP•R00T Report — C1: On-Chain Withdrawal Capital Path

Branch: WARP/ROOT/withdrawal-onchain-path
Date: 2026-05-28 15:00 Asia/Jakarta
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: The live USDC withdrawal capital-exit path — `integrations/polygon_usdc.py:transfer_usdc()` and `wallet/withdrawals.py:_attempt_onchain_transfer()` lifecycle, behind `EXECUTION_PATH_VALIDATED`.
Not in Scope: On-chain deposit sweep (still logical-only); CTF redeem (already wired at `integrations/polymarket.py:submit_live_redemption`); flipping any activation guard; Fly deploy.
Suggested Next Step: WARP•SENTINEL MAJOR validation, then owner go-live decision + staged rollout.

---

## 1. What was built

The owner directive was "prepare public-ready for LIVE, keep PAPER running."
This lane closes the last remaining LIVE blocker on the capital-exit side: the
withdrawal path that previously raised `NotImplementedError` (skeleton from
PR #1375) is now wired to a real on-chain USDC transfer — but stays a no-op in
paper mode because every code path is hard-gated behind
`EXECUTION_PATH_VALIDATED` (which remains `False`).

- New module `integrations/polygon_usdc.py` exposing `transfer_usdc(to, amount_usdc)`
  and a `PreflightError` type for pre-broadcast (no-capital-moved) refusals.
- `wallet/withdrawals.py:_attempt_onchain_transfer()` rewritten from a
  `NotImplementedError` stub into the full live settlement lifecycle, plus a
  `_settle_withdrawal()` helper that refunds the ledger on `PreflightError`.
- Auto-approval mode now settles inline in `create_withdrawal_request()` (an
  auto-approved live withdrawal would otherwise be debited but never sent).
- Migration `060_withdrawals_onchain.sql` adds the settlement columns.

## 2. Current system architecture

Capital exit (live path, guard ON):

```
admin approve_withdrawal()  [DB row: pending → approved]
        │
        ▼
_attempt_onchain_transfer()
  ├─ EXECUTION_PATH_VALIDATED == False → log deferred, return None  (PAPER: row stays 'approved', no capital moves)
  ├─ existing tx_hash?              → skip (idempotent)
  ├─ DB: status → 'processing'
  ├─ integrations.polygon_usdc.transfer_usdc(to, amount)
  │     ├─ guard re-check (EXECUTION_PATH_VALIDATED)
  │     ├─ pre-flight: gas-price ≤ INSTANT_REDEEM_GAS_GWEI_MAX
  │     ├─ pre-flight: hot-pool USDC ≥ amount  AND  MATIC ≥ 0.05
  │     ├─ build → sign (master_wallet pk) → send_raw_transaction
  │     └─ wait_for_receipt; assert status == 1
  ├─ success → DB: status 'completed' + tx_hash + processed_at; audit.write(withdrawal_onchain_sent)
  └─ raise   → DB: status 'failed' + onchain_error  (ledger debit permanent; operator reconciles)
```

Signing mirrors the already-reviewed `submit_live_redemption()` pattern
(`_get_w3()` + `master_wallet()` + legacy `gasPrice` + chainId 137 + status==1
assertion), so the live capital surface uses one consistent signing model.

RISK→EXECUTION ordering is unchanged: withdrawals debit the ledger atomically
at request time (`create_withdrawal_request`); the on-chain transfer is a
post-approval settlement and never bypasses the guard.

## 3. Files created / modified (full repo-root paths)

- CREATED: `projects/polymarket/crusaderbot/integrations/polygon_usdc.py`
- CREATED: `projects/polymarket/crusaderbot/migrations/060_withdrawals_onchain.sql`
- MODIFIED: `projects/polymarket/crusaderbot/wallet/withdrawals.py` (docstring; `_attempt_onchain_transfer` live lifecycle; `approve_withdrawal` failure → 'failed' + onchain_error)
- MODIFIED: `projects/polymarket/crusaderbot/tests/test_wallet_withdraw_flow.py` (5 new on-chain tests)

## 4. What is working

- Full suite: 1820 passed, 0 failures. `ruff check` clean; `py_compile` clean.
- New hermetic tests (all green):
  - `test_transfer_usdc_blocked_when_guard_off` — raises before any signing.
  - `test_onchain_transfer_deferred_in_paper_mode` — returns None, zero DB writes.
  - `test_onchain_transfer_completes_and_records_tx` — processing→completed, tx_hash persisted, audit written.
  - `test_onchain_transfer_idempotent_when_tx_exists` — existing tx_hash → skipped, transfer never called.
  - `test_approve_marks_failed_on_transfer_error` — failure → status 'failed' + error recorded.
- Paper-mode behavior is byte-for-byte unchanged (guard OFF returns early).

## 5. Known issues

- Post-broadcast ambiguity: if the node accepts the tx but the receipt wait
  times out, `transfer_usdc` raises a plain RuntimeError and the row is marked
  'failed' WITHOUT a refund (the transfer may have landed) — an operator
  reconciles out-of-band. Pre-broadcast failures instead raise `PreflightError`
  and auto-refund the ledger debit (no capital moved). The unique partial index
  on `tx_hash` plus the `WHERE status='pending'` approval guard make a
  double-send unreachable via the normal flow.
- Receipt-timeout is the only genuinely ambiguous failure; revert (status != 1)
  is treated conservatively as non-refundable too (operator reconciles), erring
  toward never creating money.
- On-chain sweep (`scheduler.py:sweep_deposits`) is still logical-only — the
  hot pool is only funded in a real LIVE flip via a separate guarded lane.
- `INSTANT_REDEEM_GAS_GWEI_MAX` (200) is reused as the withdrawal gas ceiling;
  a dedicated `WITHDRAWAL_GAS_GWEI_MAX` knob could be split out if desired.

## 6. What is next

- WARP•SENTINEL MAJOR validation (Phase 0–8) against this report.
- Owner go-live decision: flip `EXECUTION_PATH_VALIDATED` (+ remaining guards)
  only after SENTINEL APPROVED, with staged rollout and hot-pool funding.
- Separate guarded follow-up: wire the on-chain deposit sweep.

---

Validation Handoff (NEXT PRIORITY in PROJECT_STATE):

WARP•SENTINEL validation required for C1 on-chain withdrawal path before merge.
Source: projects/polymarket/crusaderbot/reports/forge/withdrawal-onchain-path.md
Tier: MAJOR
