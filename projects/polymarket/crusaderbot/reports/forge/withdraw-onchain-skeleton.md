# WARP•FORGE Report — withdraw-onchain-skeleton

Branch: WARP/withdraw-onchain-skeleton
Validation Tier: STANDARD
Claim Level: FOUNDATION
Validation Target: wallet/withdrawals.py — on-chain USDC transfer skeleton behind EXECUTION_PATH_VALIDATED
Not in Scope: actual polygon_usdc.py signing implementation, hot-pool key management, live gas estimation

---

## 1. What was built

On-chain withdraw signing skeleton added to `wallet/withdrawals.py`:

- `_attempt_onchain_transfer(withdrawal_id, destination_address, amount_usdc)`:
  - **Paper path** (`EXECUTION_PATH_VALIDATED=False`): logs `withdrawal_onchain_deferred` and returns. No side effects.
  - **Live path stub** (`EXECUTION_PATH_VALIDATED=True`): raises `NotImplementedError` with inline comments showing exactly where `polygon_usdc.transfer_usdc()` and the audit write should go. This makes the guard fully visible in code — it cannot be silently "live" without the actual implementation.

- `approve_withdrawal()` updated: calls `_attempt_onchain_transfer()` after DB approval is committed. Errors are caught + logged but do NOT undo the approval (debit is permanent; admin handles out-of-band reconciliation).

This follows the identical pattern as `services/redeem/redeem_router.py:_submit_live_redemption()` — the same guard check, the same log-and-return paper path, the same audit write stub.

---

## 2. Current system architecture

```
approve_withdrawal()
  ├─ UPDATE withdrawals SET status='approved' (committed)
  └─ _attempt_onchain_transfer()
       ├─ EXECUTION_PATH_VALIDATED=False → log deferred, return (paper-safe)
       └─ EXECUTION_PATH_VALIDATED=True  → NotImplementedError (live path not wired)
                                           ↓ (future)
                                           integrations/polygon_usdc.py:transfer_usdc()
                                           + audit.write("withdrawal_onchain_sent")
```

Rejection path unchanged: `reject_withdrawal()` refunds via `credit_in_conn(T_ADJUSTMENT)` — no on-chain path needed (debit was never sent).

---

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/wallet/withdrawals.py`
  - Added `_attempt_onchain_transfer()` — on-chain skeleton with guard check
  - Updated `approve_withdrawal()` to call it post-DB-commit with error isolation

Created:
- `projects/polymarket/crusaderbot/reports/forge/withdraw-onchain-skeleton.md` (this file)

---

## 4. What is working

- Paper-safe: `EXECUTION_PATH_VALIDATED=False` (default) → approval records in DB, no transfer attempt, `withdrawal_onchain_deferred` info log
- Guard visible in code: `EXECUTION_PATH_VALIDATED=True` → `NotImplementedError` logged at ERROR — no silent live path
- Approval error isolation: on-chain errors never undo DB approval
- 18/18 test_wallet_withdraw_flow.py pass; py_compile clean

---

## 5. Known issues

- `integrations/polygon_usdc.py:transfer_usdc()` is not yet implemented — this is the next activation milestone. Requires: Polygon RPC endpoint, master hot-pool private key in `.env`, gas estimation logic, tx confirmation tracking.
- `rejection_path` has no on-chain equivalent — correct for now (paper refund only). Live rejection after an on-chain transfer would require a reverse USDC transfer or separate reconciliation process — deferred until live trading.

---

## 6. What is next

- Implement `integrations/polygon_usdc.py:transfer_usdc(to, amount_usdc) → str` (tx_hash) using web3.py or ethers.js sidecar
- Uncomment the live path in `_attempt_onchain_transfer` once implemented
- Set `EXECUTION_PATH_VALIDATED=true` in fly.toml secrets after live wallet infrastructure passes SENTINEL audit
- WARP🔹CMD: review + merge + deploy this PR (paper-safe: all existing behavior unchanged)

Suggested Next Step: WARP🔹CMD review + merge. STANDARD tier.
