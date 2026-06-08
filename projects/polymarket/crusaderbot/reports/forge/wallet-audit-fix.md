# WARP-94 — Wallet System Audit + Fix

Role: WARP•R00T
Branch: WARP/wallet-audit-fix
Validation Tier: MAJOR (financial — real USDC on-chain detection path)
Claim Level: NARROW INTEGRATION (additive, credit-neutral alert path; simulated end-to-end)
Validation Target: deposit-detection + wrong-token handling on the Polygon USDC pipeline
Not in Scope: trading execution (domain/execution|strategy|risk), ENABLE_LIVE_TRADING / SCORER_ACTIVE / ORCHESTRATOR_ACTIVE, kill_switch, paper-trade ledger (trade_open/trade_close), encrypted_key handling (read-only for signing, untouched)
Suggested Next Step: WARP🔹CMD review (MAJOR, financial) → merge decision; this lane is HELD, NOT self-merged, per directive Stop Condition

---

## 1. What was built

Primary outcome of this lane is an **audit**: the deposit/withdrawal pipeline
was found **already built, idempotent, reorg-safe, and tested** — not missing as
the directive's "code completeness is unknown" assumed. The `deposits=0 /
withdrawals=0` DB state reflects *no real USDC.e has reached the addresses yet*
(paper phase), not absent code.

The one genuine gap — the deposit watcher scanned only **one** USDC contract —
was closed with a **credit-neutral wrong-token alert path** (CMD-selected
option "Detect + alert only"):

- The watcher now also scans **native USDC** (`0x3c499c…`) for transfers to any
  known deposit address.
- Native USDC is **never credited** (it is a distinct ERC-20 from Polymarket's
  USDC.e collateral, untradeable here without a swap). Instead each transfer is
  recorded once in a new `wrong_token_deposits` table and the user is alerted to
  contact support. No ledger movement, ever.
- The USDC.e credit path is **byte-unchanged** — the native pass runs on an
  independent cursor and cannot affect crediting.

## 2. Current system architecture

```
Polygon USDC.e Transfer ─┐
                         ├─► scheduler.watch_deposits() (job: deposit_watch, 120s)
                         │     ├─ polygon.scan_from_cursor(addresses, token=USDC.e)
                         │     ├─ _record_pending_deposit  → deposits(status=pending)   [idempotent ON CONFLICT(tx_hash,log_index)]
                         │     ├─ _confirm_ready_deposits   → status=confirmed @32 blocks → ledger T_DEPOSIT credit (once)
                         │     ├─ _revert_deposit           → removed=true → un-credit (reorg guard)
                         │     └─ _alert_wrong_token_deposits(addr_by_lower)   [NEW]
Polygon native USDC ─────┘           ├─ polygon.scan_from_cursor(addresses, token=NATIVE)  [cursor: usdc_native_deposits]
                                     └─ _record_wrong_token_deposit → wrong_token_deposits(ON CONFLICT DO NOTHING) + Telegram warn
                                        (NO ledger, NO balance — credit-neutral)

Withdrawal:  create_withdrawal_request → ledger debit (atomic) → approve_withdrawal
             → _settle_withdrawal → _attempt_onchain_transfer → custody.transfer_usdc
             (EOA: polygon_usdc / Safe: relayer) → status pending→approved→processing→completed|failed
             → audit + tx_hash + processed_at;  PreflightError → refund;  post-broadcast error → reconcile
```

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/config.py` — `USDC_NATIVE_POLYGON`, `WRONG_TOKEN_ALERTS_ENABLED`
- `projects/polymarket/crusaderbot/integrations/polygon.py` — optional `token_address` on `scan_usdc_transfers` / `scan_from_cursor` (default = USDC.e; existing call unchanged)
- `projects/polymarket/crusaderbot/scheduler.py` — `_alert_wrong_token_deposits`, `_record_wrong_token_deposit`, wired into `watch_deposits`

Created:
- `projects/polymarket/crusaderbot/migrations/093_wrong_token_deposits.sql` — `wrong_token_deposits` table (UNIQUE tx_hash+log_index, RLS enabled) + `usdc_native_deposits` cursor seed
- `projects/polymarket/crusaderbot/tests/test_deposit_e2e.py` — full `watch_deposits()` simulation: USDC.e records→confirms→credits-once; native USDC alerts-without-crediting + idempotent re-alert suppression

## 4. What is working

- Deposit watcher: idempotent, confirmation-depth (32) crediting, reorg revert — verified by `test_deposit_reorg.py` (4) + new `test_deposit_e2e.py` (2).
- Wrong-token native-USDC pass: detect + record + alert, **zero ledger movement**, one alert per transfer (idempotent), independent cursor.
- Withdrawal executor: full status machine, ledger debit-on-request + refund-on-preflight-fail, EOA/Safe custody dispatch — verified by `test_wallet_withdraw_flow.py`, `test_sweep_deposits.py`, `test_custody_safe.py`.
- Targeted suite: 6 deposit + 45 wallet/custody/sweep/withdraw tests pass; ruff clean on all touched files.

## 5. Known issues

- Native USDC is **detect-and-alert only** by design (CMD decision). Recovery of
  a wrong-token deposit is a **manual / operator** step — no automated return or
  swap is built. `wrong_token_deposits` is the operator audit trail.
- `WRONG_TOKEN_ALERTS_ENABLED` defaults ON; the pass is harmless (no capital
  move) but adds one extra `eth_getLogs` per 120s tick.
- `safe_address` is NULL for all 6 wallets — correct for the active
  `CUSTODY_MODE='eoa'` posture (see §6); not a defect.
- Full local suite has 9 pre-existing failures + 10 collection errors from
  optional deps absent in this sandbox (`sse_starlette`, `polymarket-client`,
  …) — confirmed present on the unchanged tree (git stash); unrelated to this
  lane. CI installs the full stack.

## 6. What is next

- **safe_address clarification (Task C):** `safe_address` is the deterministic
  Polymarket Safe-proxy (CREATE2 from the factory, `wallet/safe.py`). It is
  **OPTIONAL / future** — used **only** when `CUSTODY_MODE='safe'` (gasless
  Builder relayer). The active mode is `'eoa'` (config default), where the
  per-user EOA `deposit_address` is the custody account and NULL `safe_address`
  is correct. `backfill_safe_addresses()` populates it ahead of any Safe
  cutover; the deposit watcher already routes transfers to *either* address to
  the same user. **No code change required** — documented only.
- **End-to-end deposit test (Task D):** cannot send real USDC from CC (and the
  directive + Stop Conditions forbid it without CMD approval). Delivered as a
  **simulation** (`test_deposit_e2e.py`) proving the full DB state transition.
  Real-deposit procedure for an operator: send ≥ $1 **USDC.e**
  (`0x2791Bca…`) on Polygon to walk3r69's `deposit_address`
  `0x5827edEf918dc6bf38D5b7D7bbf0A53dF5e8F808`; within ~120s a `deposits` row
  appears (`status='pending'`), promotes to `confirmed` after 32 blocks, credits
  `wallets.balance_usdc` + a `ledger` T_DEPOSIT row, and the user gets a Telegram
  "Deposit confirmed" message. Sending **native** USDC instead yields a
  `wrong_token_deposits` row + a "Wrong token received" warning and **no**
  credit.
- **HOLD for WARP🔹CMD:** MAJOR financial lane — per directive Stop Condition,
  not merged to main pending CMD review.

Validation Handoff (NEXT PRIORITY):
```
WARP🔹CMD review required (MAJOR, financial — CMD merge decision).
Source: projects/polymarket/crusaderbot/reports/forge/wallet-audit-fix.md
Tier: MAJOR
```
