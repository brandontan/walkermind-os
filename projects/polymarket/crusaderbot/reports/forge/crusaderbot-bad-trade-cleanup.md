# WARP•FORGE REPORT — crusaderbot-bad-trade-cleanup

**Branch:** WARP/CRUSADERBOT-BAD-TRADE-CLEANUP
**Date:** 2026-05-17 (Asia/Jakarta UTC+7)
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** positions table + wallets table — walk3r69 only
**Not in Scope:** open positions, other users, trades closed after #1105 deploy

---

## 1. What Was Built

DB cleanup of 22 bad closed positions for user `walk3r69` caused by price fetch bug
(#1105). The bug returned `current_price = 0.540–0.545` on FIFA World Cup YES legs
(true market price: 3–4¢). TP triggered at incorrect exit price, inflating P&L.

Actions executed:
- Logged all 22 bad rows before deletion
- Deleted 22 positions rows (Option A — clean delete, paper mode)
- Recalculated and updated `wallets.balance_usdc` for walk3r69

---

## 2. Current System Architecture

No code change. DB-only intervention.

Affected tables:
- `public.positions` — deleted 22 rows (status=closed, exit_reason=tp_hit, current_price>=0.40)
- `public.wallets` — updated balance_usdc for walk3r69

---

## 3. Files Created / Modified

- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-bad-trade-cleanup.md` (this file — pre-delete log)

---

## 4. PRE-DELETE AUDIT LOG

**User:** walk3r69
**User UUID:** 7e6fbd20-0c7c-4f1c-bfc8-a07a396ef2ba
**Bad trade count:** 22
**Total inflated P&L:** $1,237.569157
**Wallet balance before cleanup:** $2,227.569157
**Expected wallet balance after cleanup:** $990.000000
**Window:** 2026-05-17 12:34:25 UTC → 2026-05-17 13:53:59 UTC

### Deleted Rows (position_id | market_id | current_price | pnl_usdc | closed_at)

| position_id | market_id (prefix) | current_price | pnl_usdc | closed_at (UTC) |
|---|---|---|---|---|
| 8474ec1b-3ee3-4652-ae59-1718e52f313a | 0x74dba1ce... | 0.545000 | 75.826772 | 2026-05-17 13:53:59 |
| d4c02944-a9ff-45f0-88c8-bd7bcf41b8d1 | 0x909659c9... | 0.540000 | 50.335196 | 2026-05-17 13:53:59 |
| 57f5652d-3cf9-495b-81ed-7212e6d30471 | 0xd6589172... | 0.545000 | 102.371134 | 2026-05-17 13:53:58 |
| ac6951a2-261b-4f9f-bc77-da23610db593 | 0xe6bcc2f1... | 0.540000 | 53.157895 | 2026-05-17 13:53:58 |
| bdd71214-da1b-431a-9f79-2c9c8b1a3b10 | 0xa467b14d... | 0.545000 | 68.417266 | 2026-05-17 13:50:59 |
| a198659d-c87b-4122-8b87-1145231f8ece | 0x4f3421fb... | 0.545000 | 56.060606 | 2026-05-17 13:50:59 |
| 0a3c01d0-2144-401e-92a5-778fc9e27ec8 | 0x1595b481... | 0.545000 | 95.825243 | 2026-05-17 13:50:58 |
| 6753460e-47d0-4491-b6ea-b92a1e905114 | 0x0c4cd205... | 0.545000 | 53.742690 | 2026-05-17 13:50:58 |
| b115891a-803f-43bb-9d8c-30946797496a | 0x30d55d81... | 0.540000 | 49.016393 | 2026-05-17 13:47:59 |
| 5acdc39e-c6c7-4a73-b8dd-1962c04f845f | 0x375409bc... | 0.540000 | 37.161572 | 2026-05-17 13:47:58 |
| cf8f1729-8766-490f-9ecd-c0170bbc405e | 0x713641f7... | 0.540000 | 27.894737 | 2026-05-17 13:47:58 |
| 3788d5ad-64b5-46a3-bd81-c104e59cd127 | 0x52847ca1... | 0.540000 | 70.597015 | 2026-05-17 13:47:58 |
| 0d184a8c-9300-4ae7-8f20-76bb1dcc3f9f | 0x89389a6b... | 0.540000 | 32.687747 | 2026-05-17 13:45:00 |
| 7d1b1c93-4d9f-4bac-ad4a-3e5775e6ed88 | 0xbefea666... | 0.545000 | 90.925926 | 2026-05-17 13:45:00 |
| 7572e4eb-a288-4148-b0a4-6fa238df150c | 0x0f49db97... | 0.545000 | 12.290389 | 2026-05-17 13:44:59 |
| b08503d9-32f3-41c3-80ac-2f7857299c31 | 0x9b6fef24... | 0.545000 | 20.704225 | 2026-05-17 13:44:59 |
| f052b941-d0bc-46e0-9fce-5479a932ac25 | 0x7976b8db... | 0.540000 | 22.238806 | 2026-05-17 13:41:59 |
| de02b2f3-d13e-4423-a546-a5e27d3c944c | 0xb6b3d7a2... | 0.540000 | 13.427332 | 2026-05-17 13:41:58 |
| e1462f85-203d-4099-b81b-4f0b02936e9d | 0xf8f63bb4... | 0.540000 | 3.688213 | 2026-05-17 13:41:58 |
| 445e0068-d38c-4627-9c51-dbd63b6dcd5f | 0xf7b5491e... | 0.545000 | 4.533333 | 2026-05-17 13:41:58 |
| d70ccdbf-0b98-433f-8664-95fd1ffd6ff4 | 0x3bc69cb6... | 0.545000 | 171.666667 | 2026-05-17 12:34:27 |
| 60eeef2b-9751-4b81-80d3-1305ad68e928 | 0xfe230d51... | 0.540000 | 125.000000 | 2026-05-17 12:34:25 |

**SUM CONFIRMED:** 1,237.569157 USDC

### Note — Other Affected Users (out of scope for this task)

qwneer8 and Maver1ch69 have identical bad trades (same markets, same inflated P&L pattern).
WARP🔹CMD to decide if cleanup should extend to those users.

---

## 5. What Is Working

- Pre-delete audit: 22 bad rows identified and logged
- DELETE executed: 22 positions removed
- Wallet recalculated: balance_usdc updated from $2,227.569157 → $990.000000

### Post-Delete Verification Results

| Check | Result |
|---|---|
| Wallet balance | $990.000000 ✓ |
| Remaining bad trades (tp_hit, price>=0.40) | 0 ✓ |
| Remaining closed positions | 13 (market_expired, pnl=$0 each) ✓ |
| Open positions untouched | 1 (status=open, NOT deleted) ✓ |

---

## 6. Known Issues

- qwneer8 and Maver1ch69 have the same corrupted positions — not cleaned in this lane
- Positions table has no separate `exit_price` column — buggy price stored in `current_price`

---

## 7. What Is Next

- WARP🔹CMD review required
- Decision on whether to extend cleanup to qwneer8 / Maver1ch69

---

**Suggested Next Step:** WARP🔹CMD review. Extend to other users if confirmed.
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
