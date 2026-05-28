# WARP•R00T Report — Deposit-Watcher Safe Awareness (Custody Migration Chunk 2b/4)

Branch: WARP/ROOT/deposit-watcher-safe-aware
Date: 2026-05-28 18:30 Asia/Jakarta
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: `scheduler._build_watched_addresses` + the watcher SQL — adds the user's pre-computed `safe_address` to the scan set so transfers into the Safe credit the same user as transfers into the EOA.
Not in Scope: SafeCustody transfers (Chunk 3 — needs Builder creds); cutover (Chunk 4); the on-chain Safe deploy itself.
Suggested Next Step: WARP🔹CMD review; then run `wallet.safe.backfill_safe_addresses()` post-deploy (existing users) and either proceed to Chunk 3 when credentials arrive or pause here.

---

## 1. What was built

Chunk 2b completes the address-recognition side of the custody migration: the
deposit watcher now scans **both** the EOA `deposit_address` **and** the
pre-computed `safe_address` (migration 061) for every wallet. Both addresses
route to the same `user_id`, so a USDC transfer into a user's Safe — e.g.
from a Polymarket.com Magic-link flow or any wallet that already pays into the
deterministic Safe — credits that user identically to a direct EOA deposit.

- `scheduler.py:watch_deposits` SQL now selects `safe_address` alongside the EOA.
- New `scheduler._build_watched_addresses(rows)` helper returns
  `(addresses, addr_by_lower)` including Safe addresses when set. Null
  `safe_address` rows fall back to EOA-only — pre-backfill wallets keep working
  unchanged.
- The confirmation-depth + reorg state machine (mig 047) is untouched: pending,
  confirmed, and reverted lifecycles are address-agnostic.

## 2. Current system architecture

```
watch_deposits()  (interval cron)
  ├─ SELECT user_id, deposit_address, safe_address FROM wallets
  ├─ (addresses, addr_by_lower) = _build_watched_addresses(rows)
  │     for each row: include EOA  →  user_id
  │                   include Safe →  user_id  (when not NULL)
  ├─ polygon.scan_from_cursor(addresses, cursor)
  └─ for each transfer:
        user = addr_by_lower[transfer.to.lower()]
        → _record_pending_deposit / _revert_deposit  (unchanged)
        → _confirm_ready_deposits  (unchanged; credits ledger at depth)
```

The new helper is pure: deterministic in/out, zero external dependencies, fully
unit-testable in isolation.

## 3. Files created / modified (full repo-root paths)

- MODIFIED: `projects/polymarket/crusaderbot/scheduler.py` (`_build_watched_addresses` + watcher SQL/dict build)
- MODIFIED: `projects/polymarket/crusaderbot/tests/test_wallet_safe.py` (3 new helper tests)

No migration, no new files. The `safe_address` column already exists (migration 061 shipped in #1406).

## 4. What is working

- Full suite: 1847 passed (1844 + 3 new), 0 failures. ruff + py_compile clean.
- Helper covers: EOA-only fallback when Safe is NULL; both addresses included when Safe is set; multi-user multi-address routing; lowercase normalization in the lookup.
- Watcher's reorg/confirmation logic untouched — `test_deposit_reorg.py` still passes.

## 5. Known issues

- Existing wallets still have `safe_address = NULL` until backfill runs — they
  remain EOA-only at the watcher (correct behavior; not a regression).
- A Safe deposit before that user's Safe is actually deployed on-chain is still
  recognised (the address is deterministic via CREATE2, so funds are
  recoverable once the relayer deploys the Safe in Chunk 3). This is a feature,
  not a bug.

## 6. What is next

- Run `wallet.safe.backfill_safe_addresses()` post-deploy to populate the column
  for existing users (one-shot; idempotent).
- Chunk 3 (needs Builder creds): SafeCustody transfer + sweep via the relayer.
- Chunk 4 (needs Builder creds): staged cutover to `CUSTODY_MODE='safe'`.

---

Validation Handoff (NEXT PRIORITY in PROJECT_STATE):

WARP🔹CMD review required. STANDARD tier — SENTINEL not allowed on STANDARD
per CLAUDE.md; reclassify to MAJOR for deeper validation if desired.
Source: projects/polymarket/crusaderbot/reports/forge/deposit-watcher-safe-aware.md
