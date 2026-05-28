# WARP•R00T Report — Safe-Address Pre-compute (Custody Migration Chunk 2/4)

Branch: WARP/ROOT/safe-address-precompute
Date: 2026-05-28 18:00 Asia/Jakarta
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: `wallet/safe.py` (compute_safe_address + set_safe_address_in_conn + backfill_safe_addresses), migration 061, and the vault wire-in at `wallet/vault.py:create_wallet_for_user`. EOA custody behavior unchanged.
Not in Scope: Deposit-watcher Safe awareness (Chunk 2b), SafeCustody capital paths (Chunk 3), cutover (Chunk 4). Builder credentials are still NOT required at this stage.
Suggested Next Step: WARP🔹CMD review; then either Chunk 2b (deposit-watcher Safe awareness) or proceed to Chunk 3 once credentials arrive.

---

## 1. What was built

Chunk 2 of the custody migration. The Polymarket Safe-proxy address for any
signer EOA is **deterministic** — CREATE2 from the Safe factory, computed
locally with zero network calls — so we can populate `wallets.safe_address`
for every existing and future user TODAY without waiting on Builder Program
credentials.

- New migration `061_wallets_safe_address.sql`: additive + idempotent
  `safe_address VARCHAR(42)` column + partial-unique index.
- New module `wallet/safe.py`:
  - `compute_safe_address(signer_pk)` — local CREATE2 via the SDK's
    `RelayClient.get_expected_safe()`, constructed without builder creds.
  - `set_safe_address_in_conn(conn, user_id, pk)` — inline writer used at
    wallet creation. No-ops gracefully when the SDK is missing.
  - `backfill_safe_addresses()` — idempotent batch backfill (only touches
    rows where `safe_address IS NULL`). Aborts cleanly if the SDK is absent.
  - `SafeDerivationUnavailable` — typed error for missing SDK.
- `wallet/vault.py:create_wallet_for_user` now pre-computes and stores the
  Safe address alongside the deposit-EOA insert. Harmless in EOA mode; ready
  in Safe mode.

EOA custody behavior is unchanged — paper users keep receiving deposits at
their EOA `deposit_address`. The Safe column is informational at this stage.

## 2. Current system architecture

```
NEW (this lane):
  migrations/061_wallets_safe_address.sql
      ADD COLUMN safe_address VARCHAR(42)
      CREATE UNIQUE INDEX (partial, WHERE safe_address IS NOT NULL)

  wallet/safe.py
      compute_safe_address(signer_pk)              [local CREATE2, no creds]
      set_safe_address_in_conn(conn, uid, pk)      [inline at wallet create]
      backfill_safe_addresses(batch_size=200)      [idempotent, NULL only]

  wallet/vault.py
      create_wallet_for_user(uid):
          INSERT INTO wallets ...               (unchanged)
          await set_safe_address_in_conn(...)   [NEW, on same conn]
          SELECT ...
```

Soft-import discipline: the SDK is required at compute time but its absence
is recoverable (the column stays NULL and backfill can fill it later).

## 3. Files created / modified (full repo-root paths)

- CREATED: `projects/polymarket/crusaderbot/migrations/061_wallets_safe_address.sql`
- CREATED: `projects/polymarket/crusaderbot/wallet/safe.py`
- CREATED: `projects/polymarket/crusaderbot/tests/test_wallet_safe.py` (8 tests)
- MODIFIED: `projects/polymarket/crusaderbot/wallet/vault.py` (import safe; call inline at user creation)

## 4. What is working

- Full suite: 1844 passed (1836 + 8 new), 0 failures. ruff + py_compile clean.
- Derivation is deterministic (same pk → same Safe address) and distinct
  signers map to distinct Safes. Empty key is rejected.
- Inline wallet-create wiring forwards the correct pk to the Safe writer.
- Backfill is idempotent (NULL-only WHERE clause) and reports
  `{scanned, filled, skipped}` accurately. Aborts cleanly on SDK absence.

## 5. Known issues

- Backfill is not auto-invoked. Either call it manually post-deploy or fold
  into a one-shot startup hook in a later chunk — left explicit on purpose
  to avoid scope creep into this lane.
- Existing rows already in the DB will have `safe_address = NULL` until
  backfill runs; new users get it inline. Both are correct intermediate states.

## 6. What is next

- Chunk 2b (optional): deposit-watcher learns the Safe address so deposits
  sent to the Safe (e.g., via the Polymarket.com Magic-link flow) are
  credited to the same user.
- Chunk 3 (needs Builder creds): SafeCustody transfer + sweep via the
  gasless relayer.
- Chunk 4 (needs Builder creds): staged cutover to CUSTODY_MODE='safe'.

---

Validation Handoff (NEXT PRIORITY in PROJECT_STATE):

WARP🔹CMD review required. STANDARD tier — SENTINEL not allowed on STANDARD
per CLAUDE.md; reclassify to MAJOR if you want deeper validation.
Source: projects/polymarket/crusaderbot/reports/forge/safe-address-precompute.md
