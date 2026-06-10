# per-user-deposit-wallet-persist

**Role:** WARP•R00T
**Branch:** WARP/root-per-user-deposit-wallet-persist
**Validation Tier:** MAJOR
**Claim Level:** NARROW INTEGRATION

## 1. What was built

Step 2 of the per-user on-chain execution lane (Step 1 = #1731 user_client.py; Step 1b = #1732 async hardening; Step 1c = #1734 builder fail-fast). This step persists the SDK-resolved Polymarket deposit wallet address on the `wallets` row so Step 4 (execution wiring) can enforce the #1730 §4 cross-user isolation invariant in code:

> *every per-user order build asserts `resolved_wallet == wallets.polymarket_deposit_wallet`; refuse to sign on drift*

Without this column, Step 4 has no stable address to compare against — it would have to re-derive on every order and trust the result, which means a keying bug or wallet migration could silently sign user A's order with user B's funds.

## 2. Current system architecture

```
signup → vault.create_wallet_for_user(uid)
           ├─ next_hd_index()
           ├─ derive_address (HD m/44'/60'/0'/0/idx)
           ├─ encrypt_pk → INSERT wallets row
           ├─ set_safe_address_in_conn  (CREATE2 Safe proxy — migration 061)
           └─ set_deposit_wallet_in_conn  ★ NEW
                 └─ resolve_deposit_wallet(pk)  ★ NEW
                       └─ polymarket.AsyncSecureClient.create(pk, wallet=None)
                             • on-chain factory check (beacon vs UUPS)
                             • reads sc.wallet ONLY — never .credentials
                             • close()

backfill_deposit_wallets()  ★ NEW
  └─ SEQUENTIAL loop over wallets WHERE polymarket_deposit_wallet IS NULL
        (no asyncio.gather per #1730 Gemini advisory — every iteration drives
         one polymarket API call + one DB write; parallel fan-out would
         stampede both the DB pool and the Polymarket SDK)
```

Step 4 (future) will read `wallets.polymarket_deposit_wallet` at order time and assert it against `get_user_clob_client(uid).wallet`.

## 3. Files created / modified

* **NEW** `projects/polymarket/crusaderbot/migrations/094_wallets_polymarket_deposit_wallet.sql` — additive + idempotent: `ALTER TABLE wallets ADD COLUMN IF NOT EXISTS polymarket_deposit_wallet VARCHAR(42)` + unique partial index for reverse-lookup. Mirrors migration 061 (safe_address) shape.
* **MODIFIED** `projects/polymarket/crusaderbot/integrations/clob/user_client.py` — added `resolve_deposit_wallet(private_key) -> str`: wallet-only resolver that drives `AsyncSecureClient.create(pk, wallet=None)` and reads `sc.wallet` ONLY (never touches `sc.credentials`, which mints L2 API keys server-side — backfill must NOT rotate creds as a side effect of one-shot address population). Exported via `__all__`.
* **NEW** `projects/polymarket/crusaderbot/wallet/deposit_wallet.py` — mirror of `wallet/safe.py`:
  - `DepositWalletDerivationUnavailable` typed sentinel (distinct from `SafeDerivationUnavailable`)
  - `_resolve` thin wrapper mapping `ImportError → DepositWalletDerivationUnavailable`
  - `set_deposit_wallet_in_conn(conn, user_id, signer_pk)` — inline call from vault; defensive (transient resolve failure logs + returns None so wallet creation always lands; backfill is the safety net)
  - `backfill_deposit_wallets(batch_size=200)` — sequential, idempotent
* **MODIFIED** `projects/polymarket/crusaderbot/wallet/vault.py` — imports `set_deposit_wallet_in_conn` and calls it inline in `create_wallet_for_user` directly after `set_safe_address_in_conn` (same scope-of-pk window).
* **NEW** `projects/polymarket/crusaderbot/tests/test_deposit_wallet_persist.py` — 9 tests pinning the contract (conn writer happy path / SDK missing / transient failure / empty-key propagation / backfill idempotency / backfill aborts cleanly on SDK unavailable / backfill continues past per-user failure / vault wiring).

## 4. What is working

* `pytest` — 52 pass (9 new + 43 inherited from wallet_safe / user_clob_client / users / wallet_backfill) + 3 skipped (pre-existing — environment without `py_builder_relayer_client`).
* Wider wallet/vault/deposit/custody/withdrawal regression: 162 pass + 3 skipped pre-existing.
* `ruff check` clean on all 4 touched files.
* Vault wiring proven by `test_create_wallet_pre_resolves_deposit_wallet`: `set_deposit_wallet_in_conn` is called with the UNENCRYPTED private key (so the SDK can sign), not the encrypted blob.
* SDK-unavailable + transient resolve failure paths: both log + return None, NEVER raise — wallet creation must succeed in environments without the polymarket SDK installed (CI smoke tests, paper-only runs) and during Polymarket API outages.
* `PerUserClobError` for empty signer key propagates via the explicit `except PerUserClobError: raise` clause (not swallowed by the broad transient-failure catch — that's a programmer bug, not environmental).
* Backfill SEQUENTIAL invariant: `resolve_mock.await_count == 2` for two rows (asserted in `test_backfill_idempotent_and_counts_correctly`).

## 5. Known issues

* **Existing users start NULL.** Migration 094 is additive; existing wallets have `polymarket_deposit_wallet = NULL` until `backfill_deposit_wallets()` runs. Step 4 must tolerate NULL during the rollout window (fall through to direct SDK resolution) OR the backfill must run + complete before Step 4's assertion goes hard. Owner / Step 4 design decision.
* **Backfill is operator-triggered.** This lane does NOT auto-run the backfill at boot (a stampede risk for a large user base, and it would lengthen boot time on every redeploy). An ops script entrypoint (`scripts/backfill_deposit_wallets.py`) is a small follow-up if owner wants automation; for now the function is callable from a shell.
* **`polymarket` SDK availability.** If the SDK is missing in production (it shouldn't be — `pyproject` pins it), both inline + backfill paths NO-OP gracefully. The Step 4 assertion would then trip — guard required.

## 6. What is next

1. Operator runs `backfill_deposit_wallets()` once after migration 094 applies.
2. **Step 3** — deposit watcher learns to recognise `polymarket_deposit_wallet` as a credit-target (mirror of `safe_address` in `scheduler._build_watched_addresses`). Small scope.
3. **Step 4** — execution wiring: `router.execute` / `live.place_order` thread `user_id` through and call `get_user_clob_client(user_id)`; assert `client.wallet == wallets.polymarket_deposit_wallet` before signing. The original #1730 design step.
4. **Step 5** — WARP•SENTINEL gate before live per-user trading.

Live trading remains owner-gated regardless (`ENABLE_LIVE_TRADING` + 5 activation guards + the upstream EIP-7702 L1 auth wall covered in the previous lane).

## Metadata

* **Validation Target:** the new column is populated atomically with wallet creation; the wallet-only resolver never mints L2 creds; backfill is sequential + idempotent; vault wiring forwards the unencrypted pk.
* **Not in Scope:** Step 4 execution wiring; the pre-post assertion; deposit-watcher Step 3 awareness; an ops backfill script; auto-backfill at boot; any change to `resolve_deposit_wallet_creds` / `get_user_clob_client` / the per-user cache; the L1 auth byte encoding (unchanged — owner-gated upstream wall); risk constants / Kelly / `ENABLE_LIVE_TRADING` / `USE_REAL_CLOB` / `USE_CLOB_V2` / kill switch / strategy entry-exit.
* **Suggested Next Step:** owner runs migration 094 + the backfill on the next deploy, then Step 3 (deposit watcher awareness) ships as a separate ~50-line lane.
