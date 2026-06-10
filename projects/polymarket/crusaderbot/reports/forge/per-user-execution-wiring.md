# per-user-execution-wiring

**Role:** WARP•R00T
**Branch:** WARP/root-per-user-execution-wiring
**Validation Tier:** MAJOR
**Claim Level:** NARROW INTEGRATION

## 1. What was built

Step 4 of the per-user on-chain execution lane (after #1731 user_client / #1732 async hardening / #1734 builder fail-fast / #1736 deposit-wallet persistence / #1738 Rust sidecar / #1739 staging harness toggle / #1740 watcher Step 3). The SAFETY-CRITICAL piece — every per-user live order resolves the user's CLOB client and asserts in code that the SDK-resolved deposit wallet matches the persisted `wallets.polymarket_deposit_wallet` column BEFORE any broker call.

This is the #1730 §4 cross-user isolation invariant moved from policy to a runtime assertion: *"a keying bug here = user A's order built with user B's funds"* — caught and refused, not signed.

## 2. Current system architecture

```
risk gate (RISK before EXECUTION, unchanged) — every per-user-live order
   └─ router.execute()
        └─ live.execute(user_id, ...)
              ├─ (default: USE_PER_USER_EXECUTION=False)
              │      → get_clob_client(s)               ← byte-unchanged
              └─ (flip: USE_PER_USER_EXECUTION=True)
                     → resolve_user_clob_client(         ← NEW
                           user_id=user_id, conn=conn, settings=s,
                       )
                       ├─ get_user_clob_client_with_wallet(uid, s)  ← NEW
                       │     • single-flight cache hit per user
                       │     • returns (client, sdk_resolved_wallet)
                       ├─ SELECT polymarket_deposit_wallet FROM wallets
                       │     WHERE user_id = $1
                       │     • SAME conn as the idempotency claim
                       │       → wallet read + INSERT see ONE snapshot
                       ├─ NULL column → ClobConfigError
                       │     (operator must run backfill_deposit_wallets()
                       │      after migration 094 before flipping the flag)
                       ├─ resolved.lower() != stored.lower()
                       │     → WalletIdentityMismatch  ← REFUSE TO SIGN
                       └─ match → return client → post_order(...)

live.close_position(): same per-user path so the SELL is signed by the
   wallet that holds the position (a global-client close would sign with
   the wrong funder and the broker would reject the order).
```

## 3. Files created / modified

* **NEW** `domain/execution/per_user_clob.py` — `resolve_user_clob_client(user_id, conn, settings)` + typed `WalletIdentityMismatch` subclass of `PerUserClobError`. The wallet identity check is the whole SAFETY contract; everything else is plumbing.
* **MODIFIED** `integrations/clob/user_client.py` — exported `get_user_clob_client_with_wallet(user_id, settings) -> tuple[client, wallet]` so callers can read the SDK-resolved address without a second SDK trip. Single-flight + LRU cache contract is untouched; the new function reads the same `_CachedClient` row populated by the existing build path.
* **MODIFIED** `domain/execution/live.py` — `execute()` and `close_position()` both branch on `USE_PER_USER_EXECUTION`. The resolver call lives INSIDE the same transaction as the idempotency-claim `INSERT INTO orders`, so the wallet read and the claim see one DB snapshot (no read-then-claim race against a concurrent backfill or column update). `getattr(s, "USE_PER_USER_EXECUTION", False)` keeps every test-stub Settings backwards-compatible.
* **MODIFIED** `config.py` — `USE_PER_USER_EXECUTION: bool = False` with rollout preconditions documented in the comment (backfill complete + per-user SENTINEL + `ENABLE_LIVE_TRADING`).
* **NEW** `tests/test_per_user_clob_resolver.py` — 8 hermetic tests pin the resolver contract (match / case-insensitive match / drift / non-UUID user_id / NULL column / empty-string column / missing wallets row / `get_user_clob_client_with_wallet` returns the (client, wallet) pair).
* **NEW** `tests/test_live_per_user_wiring.py` — 3 integration tests pin the dispatch (flag ON → resolver / flag OFF → legacy global / explicit `clob_client=` always wins). Uses `contextlib.ExitStack` to compose the patch stack so the test reads as a single `with`.

## 4. What is working

* `pytest` 109 across new + adjacent (test_live_per_user_wiring + test_per_user_clob_resolver + test_user_clob_client + test_live_execution_rewire + test_live_gate_hardening) all green.
* `ruff check` clean on every touched file.
* Wallet-identity assertion uses case-insensitive compare (Ethereum checksums vs lowercase storage), so a real-world checksum mismatch never false-positives.
* Default config is byte-identical — `getattr(s, "USE_PER_USER_EXECUTION", False)` keeps the legacy single-wallet path active for every existing Settings stub.
* The injected-`clob_client` escape hatch overrides BOTH the flag and the global factory — staging harnesses, unit tests, and any explicit invocation site are never silently rerouted through the per-user resolver.

## 5. Known issues

* **`UUID` round-trip on the close path.** `position["user_id"]` is `Any` by type; the resolver requires a `UUID`. The wiring does `UUID(str(position["user_id"]))` — defensive, but a regression in the type of that column would land a `ValueError` here rather than at the source. A small follow-up could tighten the position-row type guarantee.
* **No JIT backfill.** A NULL column raises `ClobConfigError` rather than auto-resolving the wallet via the SDK and writing it. Choice is intentional — the trading hot path is the WORST place to mint new server-side state — but it means the operator MUST run `backfill_deposit_wallets()` after migration 094 before flipping the flag.
* **`close_position` per-user path uses a SECOND connection.** Unlike `execute`, the close path opens a fresh `pool.acquire()` for the resolver. That's race-free vs Step 2's idempotent backfill (NULL → set), but the snapshot is not shared with the position-row read. A follow-up could thread the existing conn through.

## 6. What is next

1. **Step 5** — WARP•SENTINEL gate before flipping `USE_PER_USER_EXECUTION=true` in prod. Validate the assertion fires on a real drift (modify `wallets.polymarket_deposit_wallet` in staging, attempt an order, confirm refuse).
2. Operator runs `backfill_deposit_wallets()` once after the next CD pushes migration 094 (already scheduled per the live-trade-readiness audit NEXT PRIORITY).
3. Owner flips `USE_PER_USER_EXECUTION=1` in Fly secrets after SENTINEL is green + backfill complete + `ENABLE_LIVE_TRADING` is owner-enabled.
4. The per-user lane is **complete on the code side** after this step. Remaining work is operational gates only.

## Metadata

* **Validation Target:** every per-user live order asserts `resolved_wallet == wallets.polymarket_deposit_wallet` before signing; drift refuses; NULL column hard-fails with an actionable message; default config is byte-unchanged.
* **Not in Scope:** the WARP•SENTINEL validation (Step 5); the staging proof dispatch; flipping any flag; the single-wallet path; the per-user public API surface (`resolve_deposit_wallet_creds`, `get_user_clob_client`, `PerUserClobError`, `PerUserClobIsolationError`, `USER_CACHE_CAPACITY`, `clear_user_clob_cache`); risk constants / Kelly / `ENABLE_LIVE_TRADING` / kill switch / strategy entry-exit / migrations.
* **Suggested Next Step:** owner schedules the WARP•SENTINEL validation lane (a small `domain/execution/per_user_clob.py` drift-injection harness against the staging app would close the loop in ~30 lines).
