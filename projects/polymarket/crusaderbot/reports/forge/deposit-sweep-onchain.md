# WARP•R00T Report — On-Chain Deposit Sweep (Hot-Pool Consolidation)

Branch: WARP/ROOT/deposit-sweep-onchain
Date: 2026-05-28 16:30 Asia/Jakarta
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: `integrations/polygon_usdc.py` (sweep_usdc_to_master + _send_native_matic) and `scheduler.py:_sweep_deposits_onchain`, double-gated behind EXECUTION_PATH_VALIDATED + SWEEP_ONCHAIN_ENABLED.
Not in Scope: Migrating custody to Gnosis-Safe proxy wallets + Polymarket Builder relayer (gasless) — documented as the future-native optimization but a separate large initiative; flipping any guard; Fly deploy.
Suggested Next Step: WARP•SENTINEL MAJOR validation, then owner decides go-live + sweep enablement.

---

## 1. What was built

The on-chain deposit sweep that funds the master hot-pool from per-user deposit
wallets. Previously `scheduler.sweep_deposits()` was accounting-only (flipped
`deposits.swept`); the real consolidation was deferred. This wires it — behind
TWO guards so it stays dormant in paper and even after a go-live flip until an
operator explicitly enables it.

Design rationale (per Polymarket skill review): the bot uses plain **EOA**
wallets (master EOA + per-user EOA HD deposit addresses), not Gnosis-Safe/Proxy
wallets, and holds no Builder Program credentials — so Polymarket's gasless
relayer (which operates on Safe/Proxy wallets) does not fit the current custody
model. For an EOA architecture the correct self-funding design is a
master-funded gas top-up sweep: deposit wallets hold only bridged USDC and no
MATIC, so the master tops up gas before each wallet signs its USDC transfer.

## 2. Current system architecture

```
sweep_deposits()  (nightly cron, max_instances=1)
  ├─ EXECUTION_PATH_VALIDATED && SWEEP_ONCHAIN_ENABLED == False
  │     → logical-only: UPDATE deposits SET swept=TRUE (unchanged paper path)
  └─ both True → _sweep_deposits_onchain()
        for each user with confirmed unswept deposits (sequential):
          pk = vault.get_decrypted_pk(user_id)
          sweep_usdc_to_master(deposit_address, pk):
            ├─ guard re-check (both flags)
            ├─ read on-chain USDC balance; skip if < SWEEP_MIN_USDC (dust)
            ├─ gas-price ceiling (INSTANT_REDEEM_GAS_GWEI_MAX)
            ├─ if wallet MATIC < SWEEP_GAS_TOPUP_MATIC:
            │     _send_native_matic(master → wallet)  [guarded by master balance]
            ├─ sign USDC transfer(wallet → master, full balance) with wallet pk
            └─ wait receipt; assert status == 1
          on confirmed tx → UPDATE deposits SET swept=TRUE for that user
          on PreflightError/Exception → log + skip (one bad wallet never aborts the run)
```

Sequential execution (cron is `max_instances=1`) means the master wallet's
gas-top-up nonces never race. Asyncio only; no threading.

## 3. Files created / modified (full repo-root paths)

- MODIFIED: `projects/polymarket/crusaderbot/integrations/polygon_usdc.py` (ERC20_ABI += balanceOf; _send_native_matic; sweep_usdc_to_master)
- MODIFIED: `projects/polymarket/crusaderbot/scheduler.py` (sweep_deposits branch + _sweep_deposits_onchain)
- MODIFIED: `projects/polymarket/crusaderbot/config.py` (SWEEP_ONCHAIN_ENABLED=False, SWEEP_MIN_USDC=1.0, SWEEP_GAS_TOPUP_MATIC=0.05)
- MODIFIED: `projects/polymarket/crusaderbot/tests/test_sweep_deposits.py` (logical-branch settings patch + 4 on-chain tests)

No migration needed — uses existing `deposits` / `wallets` columns.

## 4. What is working

- Full suite: 1827 passed, 0 failures. ruff + py_compile clean.
- New tests: sweep blocked when flag off; consolidation marks swept + audits;
  dust-skip does not mark swept; per-user failure isolation (good user still swept).
- Paper behavior unchanged: guards OFF → logical-only branch (verified by the
  existing two regression tests, now with an explicit guards-OFF settings stub).
- No private key is ever logged.

## 5. Known issues

- Leftover MATIC dust accumulates in user wallets after a top-up (top-up minus
  gas actually used). Negligible; a future enhancement could sweep residual MATIC.
- Post-broadcast ambiguity on the USDC transfer (receipt timeout) → that user is
  skipped and retried next run; the deposit stays `swept=FALSE`, so no
  double-credit, but a genuinely-landed-but-timed-out tx could be re-attempted.
  Acceptable for a guarded, operator-enabled, SENTINEL-gated rollout.
- Native-relayer (gasless) path not used — requires Safe/Proxy custody + Builder
  creds; tracked as the Polymarket-native future optimization.

## 6. What is next

- WARP•SENTINEL MAJOR validation.
- Owner go-live: after SENTINEL APPROVED, fund master MATIC, flip
  EXECUTION_PATH_VALIDATED, then enable SWEEP_ONCHAIN_ENABLED for a small cohort
  and observe before broad enablement.

---

Validation Handoff (NEXT PRIORITY in PROJECT_STATE):

WARP•SENTINEL validation required for on-chain deposit sweep before merge.
Source: projects/polymarket/crusaderbot/reports/forge/deposit-sweep-onchain.md
Tier: MAJOR
