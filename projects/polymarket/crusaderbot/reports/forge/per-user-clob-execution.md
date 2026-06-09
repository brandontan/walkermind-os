# WARP•R00T Design — per-user on-chain CLOB execution

- Validation Tier: MAJOR (per-user real-money key custody + live order execution)
- Claim Level: FOUNDATION (design/architecture only — NO runtime code in this doc; the prescribed "design before code" step for a MAJOR, security-sensitive lane)
- Validation Target: the architecture, security model, and incremental step plan below — for WARP🔹CMD/owner review before implementation begins.
- Not in Scope (this doc): any code change; the per-user deposit funding/bridge mechanics (owner decision, §5); gasless vs per-user gas (owner decision, §5).
- Suggested Next Step: owner reviews the security model (§4) + the funding/gas decisions (§5); merge #1729 (the auto-derive foundation) first; then implement Step 1.

---

## 0. Goal (owner-chosen model)

Each user trades from **their own** Polymarket deposit wallet — their own key, their
own on-chain funds, true isolation. Per-user live activation already exists
(global toggle + per-user opt-in/readiness); this lane makes the **on-chain
execution** per-user too, replacing today's single shared trading wallet.

## 1. Current state (verified)

- **Execution is single-wallet today:** `domain/execution/live.py` builds the order
  client via `get_clob_client(s)` — one configured `POLYMARKET_PRIVATE_KEY` /
  funder (`0xe82cAf…441E`). ALL real orders execute from that one wallet.
- **Per-user wallets already exist (custody):** `wallet/vault.py` —
  `create_wallet_for_user(user_id)` derives a per-user HD EOA (deposit_address,
  hd_index, **encrypted_key**); `get_decrypted_pk(user_id)` decrypts that key
  (using `WALLET_ENCRYPTION_KEY`). These back deposits/withdrawals today.
- **Deposit-wallet trading is proven (single wallet):** PR #1727 (merged) +
  #1729 (auto-derive, open) — given a key, `AsyncSecureClient` resolves that
  signer's deterministic Polymarket deposit wallet + mints its CLOB creds, and
  `ClobV2Client` places the order (sig type 3). **This is the per-user foundation:**
  the same resolution, run per user key, yields each user's deposit wallet + creds.

## 2. Target architecture

```
order for user U:
  pk_U      = vault.get_decrypted_pk(U)            # in-memory only, never logged
  wallet_U, creds_U = resolve_deposit_wallet(pk_U) # AsyncSecureClient (per-user, cached)
  client_U  = ClobV2Client(private_key=pk_U, funder=wallet_U, creds=creds_U, sig_type=3)
  client_U.post_order(...)                         # maker = U's deposit wallet
```

- **New `get_user_clob_client(user_id, settings)`** — the per-user analogue of
  `get_clob_client`. Resolves + caches per-user (keyed by `user_id`) creds + wallet
  + client.
- **Per-user cred/wallet cache** — replace the module-global `_derived` /
  `_derived_wallet` (single-wallet) with a `dict[user_id -> {creds, wallet}]`.
  Existing globals stay for the single-wallet/operator path (back-compat).
- **Onboarding** — when `create_wallet_for_user` runs, ALSO resolve + persist the
  user's Polymarket deposit wallet address (migration: `wallets.polymarket_deposit_wallet`).
  So each user row carries EOA + deposit wallet.
- **Execution rewiring** — `router.execute` / `live.py` thread `user_id` and call
  `get_user_clob_client(user_id)` instead of the global `get_clob_client(s)`.

## 3. Incremental steps (each independently safe + testable)

1. **Foundation (no execution change):** `resolve_deposit_wallet_creds(private_key)`
   extracted from #1729's `ensure_clob_credentials`; per-user cache;
   `get_user_clob_client(user_id)`. Unit-tested with a mocked SDK. (Depends on #1729.)
2. **Onboarding persistence:** migration + `create_wallet_for_user` resolves &
   stores `polymarket_deposit_wallet`; backfill job for existing users.
3. **Deposit routing (owner-gated, §5):** ensure a user's deposit lands in *their*
   Polymarket deposit wallet on-chain (not just ledger-credited).
4. **Execution rewiring:** thread `user_id` → per-user client in router/live;
   keep the single-wallet path as fallback behind a flag during rollout.
5. **Per-user staging proof:** the WARP-74 harness, parameterized by a user key,
   proves a per-user wallet places + cancels a resting order (`allow_fills=false`).
6. **Gradual rollout:** per-user opt-in (already built) gates who is live; start
   with one user, expand.

## 4. Security model (the part that must NOT be rushed)

- **Cross-user isolation is the #1 invariant.** A keying bug (user A's client built
  with user B's key) = user A trades user B's funds = catastrophic. The per-user
  cache MUST be keyed by `user_id` with no shared mutable global; every order path
  asserts the resolved wallet matches the user's stored `polymarket_deposit_wallet`
  before posting. Dedicated cross-user isolation tests required.
- **Key handling:** `get_decrypted_pk` result lives in-memory only, scoped to client
  construction; NEVER logged, NEVER in errors/audit (the `encrypted_key` constraint).
- **Per-user creds** derived via per-user `AsyncSecureClient` — never the shared
  `_derived` global.
- **All existing gates still apply per-user, unchanged:** `ENABLE_LIVE_TRADING` +
  global toggle + per-user opt-in/readiness; risk gate (Kelly 0.25, position/loss/
  drawdown caps); kill switch; idempotency. Per-user execution does NOT bypass any.
- **Custody reality:** the bot already custodies every user key (existing model);
  this lane uses them for trading, raising the stakes — warrants a SENTINEL audit
  before live.

## 5. Owner decisions required before implementing past Step 2

- **Funding/bridge:** how does each user's deposit reach their *on-chain* Polymarket
  deposit wallet? (Today deposits credit a per-user ledger; on-chain per-user
  trading needs funds physically in each user's deposit wallet.)
- **Gas:** each deposit-wallet order needs gas — per-user POL funding, or
  Polymarket's gasless relayer (the SDK supports `setup_gasless_wallet`)?
- **SENTINEL gate:** given per-user real-money keys, require a WARP•SENTINEL audit
  (cross-user isolation + key handling) before the first live per-user order.

## 6. Risks / open questions

- Per-user gas + funding routing is non-trivial and owner-policy-dependent (§5).
- Decryption-per-order cost → mitigated by caching the per-user client.
- Existing single-wallet path retained behind a flag for safe rollback.
