# WARP•R00T Report — SafeCustody + Cutover Dispatch (Custody Migration Chunks 3+4/4)

Branch: WARP/ROOT/safe-custody-cutover
Date: 2026-05-28 19:30 Asia/Jakarta
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: `wallet/custody.py` (dispatcher + SafeCustody) and the call-site swaps in `wallet/withdrawals.py:_attempt_onchain_transfer` and `scheduler._sweep_deposits_onchain`. Triple-gated behind `EXECUTION_PATH_VALIDATED` + `CUSTODY_MODE='safe'` + relayer-configured.
Not in Scope: Builder Program credential acquisition (owner; polymarket.com/settings?tab=builder); actual on-chain validation against the live relayer; Safe wallet on-chain deploy (the relayer handles this on first execute).
Suggested Next Step: WARP•SENTINEL MAJOR validation, then operator-side go-live (acquire Builder creds → set as Fly secrets → flip USE_BUILDER_RELAYER → flip CUSTODY_MODE='safe' for a small cohort → observe).

---

## 1. What was built

The final code chunks of the gasless / Safe-proxy custody migration land
together: a dispatcher selects the active custody backend per-call, and a new
`SafeCustody` class routes capital operations through the Polymarket Builder
relayer (gasless, via the user/master Safe proxies). Default `CUSTODY_MODE='eoa'`
means **nothing changes** at runtime — every call still goes to the merged C1
(withdraw) and #1403 (sweep) EOA paths. PAPER is untouched.

- New `wallet/custody.py`:
  - `transfer_usdc(to, amount)` / `sweep_usdc_to_master(from_address, from_pk)`
    dispatchers — route to `polygon_usdc.*` in EOA mode or `SafeCustody.*` in
    Safe mode.
  - `_ensure_safe_mode_wired()` raises `BuilderRelayerUnavailable` if
    `CUSTODY_MODE='safe'` but the relayer is unconfigured — **no silent
    fallback** to EOA (operator misconfiguration is a loud failure).
  - `SafeCustody.transfer_usdc` — withdrawal payout from the master Safe via
    `RelayClient.execute([SafeTransaction])`. Pre-flight: amount > 0,
    `EXECUTION_PATH_VALIDATED`, relayer configured, master-Safe USDC ≥ amount.
  - `SafeCustody.sweep_usdc_to_master` — user Safe → master Safe sweep (no MATIC
    top-up needed; the relayer pays gas). Pre-flight: both
    `EXECUTION_PATH_VALIDATED` + `SWEEP_ONCHAIN_ENABLED`, relayer configured,
    signer key non-empty. Dust skip below `SWEEP_MIN_USDC`.
  - `_execute_usdc_transfer` — encodes ERC-20 `transfer(to, amount)` via web3
    v7 `encode_abi`, submits as a `SafeTransaction(OperationType.Call, ...)`,
    waits via `asyncio.to_thread(response.wait)` so the sync SDK never blocks
    the event loop.
- Call-site dispatch:
  - `wallet/withdrawals.py:_attempt_onchain_transfer` now imports
    `transfer_usdc` from `wallet.custody` instead of `polygon_usdc`.
  - `scheduler._sweep_deposits_onchain` imports `PreflightError` + `sweep_usdc_to_master`
    from `wallet.custody`; the EOA branch is preserved bit-for-bit.

## 2. Current system architecture

```
              ┌─────────────────────────────────────┐
withdrawals.  │ wallet/custody.py dispatcher        │
_settle_with- │                                     │
drawal()  ───▶│  if CUSTODY_MODE == "safe":         │
              │      _ensure_safe_mode_wired()      │
              │      → SafeCustody.transfer_usdc    │  (gasless, relayer pays)
scheduler.    │  else:                              │
_sweep_       │      → polygon_usdc.transfer_usdc   │  (master-funded, EOA)
deposits_     │                                     │
onchain() ───▶│  (same fork for sweep_usdc_to_      │
              │   master)                           │
              └─────────────────────────────────────┘

Triple gate for Safe mode:
  1. EXECUTION_PATH_VALIDATED  (existing capital activation guard)
  2. CUSTODY_MODE == "safe"    (default "eoa")
  3. is_relayer_configured()   (USE_BUILDER_RELAYER + 3 builder creds)
Missing any of (2) or (3) while the others are set → BuilderRelayerUnavailable.
```

## 3. Files created / modified (full repo-root paths)

- CREATED: `projects/polymarket/crusaderbot/wallet/custody.py` (dispatcher + SafeCustody + helpers)
- CREATED: `projects/polymarket/crusaderbot/tests/test_custody_safe.py` (13 tests)
- MODIFIED: `projects/polymarket/crusaderbot/wallet/withdrawals.py` (`_attempt_onchain_transfer` import swap)
- MODIFIED: `projects/polymarket/crusaderbot/scheduler.py` (`_sweep_deposits_onchain` import swap)
- MODIFIED: `projects/polymarket/crusaderbot/tests/test_wallet_withdraw_flow.py` (`_settings` adds `CUSTODY_MODE='eoa'`)
- MODIFIED: `projects/polymarket/crusaderbot/tests/test_sweep_deposits.py` (settings mocks + `_config.get_settings` patches)

## 4. What is working

- Full suite: 1860 passed (1847 + 13 new), 0 failures. ruff + py_compile clean.
- Dispatcher routing: EOA (default) → polygon_usdc; Safe + configured → SafeCustody; Safe + unconfigured → loud BuilderRelayerUnavailable (no silent EOA fallback).
- SafeCustody guards: EXECUTION_PATH_VALIDATED, non-positive amount, relayer-configured, master-Safe balance pre-flight, empty signer key, dust skip.
- The sync relayer SDK is wrapped in `asyncio.to_thread` for both `execute` and `response.wait` — event loop never blocks.

## 5. Known issues

- Without Builder credentials, SafeCustody is exercised only via mocks — the
  actual network round-trip to the relayer cannot be validated in this PR. The
  triple gate ensures the path never activates without credentials, so the
  PAPER + EOA-live posture remains safe.
- `response.wait()` returning None is treated as a hard failure (RuntimeError);
  the receipt-ambiguity surface mirrors the EOA path's existing handling.
- A Safe on-chain deploy on the user side happens implicitly on first
  `execute()` call (Polymarket relayer auto-deploys) — no separate code path
  required, but the first sweep per user will include the deploy cost (covered
  by the relayer's gas).

## 6. What is next

- WARP•SENTINEL MAJOR validation.
- Owner-side operational: acquire Builder credentials at
  `polymarket.com/settings?tab=builder`; set `POLY_BUILDER_API_KEY` /
  `POLY_BUILDER_SECRET` / `POLY_BUILDER_PASSPHRASE` as Fly secrets; flip
  `USE_BUILDER_RELAYER=true`; for go-live, flip `CUSTODY_MODE='safe'` for a
  small cohort first and observe `safe_transfer_usdc_confirmed` +
  `safe_sweep_confirmed` audits before broader enablement.

---

Validation Handoff (NEXT PRIORITY in PROJECT_STATE):

WARP•SENTINEL validation required for SafeCustody + cutover dispatch before merge.
Source: projects/polymarket/crusaderbot/reports/forge/safe-custody-cutover.md
Tier: MAJOR
