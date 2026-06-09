# WARP•R00T Report — deposit-wallet-1271-auth

- Validation Tier: MAJOR (CLOB auth + order-placement path; gates whether the bot can trade migrated wallets)
- Claim Level: NARROW INTEGRATION (corrected POLY_1271 L1 auth + sig-type-3 wiring + staging-proof scaffolding; the order-signature path is the SDK's, unchanged)
- Validation Target: `integrations/clob/deposit_wallet_auth.py` (ERC-7739-wrapped ClobAuth L1 signature + `derive_or_create_deposit_wallet_creds`), its wiring in `v2_client._build_client` for `signature_type == 3`, and the staging-proof scaffolding (`git_ref` / `funder_override` / `signature_type='3'` + pre-order diagnostics).
- Not in Scope: the POLY_1271 **order** signature (already correct in the SDK), any non-1271 auth path (EOA/POLY_PROXY/GNOSIS_SAFE untouched), the live flip (`ENABLE_LIVE_TRADING` / `allow_fills`), and a real-money fill test (all owner-gated).
- Suggested Next Step: dispatch `staging-proof-fly.yml` with `ref=WARP/root-deposit-wallet-1271-auth`, `signature_type='3'`, `funder_override=0x3feC63402DfF02EdD1bEd25774e0b53c147606A9`, `use_clob_v2=true`, `allow_fills=false`, `region=nrt`; merge to main only if the order is accepted on the deposit wallet.

---

## 1. What was built

A corrected **L1 authentication path for Polymarket POLY_1271 "deposit wallets"**
(the EIP-7702 / ERC-4337 smart accounts every Magic-Link / email account was
migrated to after 2026-04-28), plus the staging-proof scaffolding to validate it
on the real broker without merging experimental crypto to `main`.

Root cause (evidenced, on-chain + upstream):

* The staging account is fully active (deposits, withdrawals, and "Bitcoin Up or
  Down" trades in its Polymarket history) — the earlier "wallet not registered"
  theory was wrong.
* On-chain (Polygon, public RPC): the legacy proxy `0xe82cAf…441E` has
  `owner() == 0xC5CFe43…88294` (the Magic EOA), so the legacy setup (sig type 1)
  was correct. But the account's deposit wallet `0x3feC63…606A9` carries code
  `0xef0100…` — the **EIP-7702 delegation marker** — and resolves to an
  ERC-4337 / EIP-1271 smart account (`isValidSignature` `0x1626ba7e`, `execute`
  `0xb61d27f6`, `validateUserOp` `0x19822f7c`, `entryPoint` `0xb0d691fe`).
* The CLOB rejects the legacy proxy as a maker now
  (`maker address not allowed, please use the deposit wallet flow`).
* Upstream (`Polymarket/py-clob-client-v2` issues #52/#53/#64/#70/#71, all OPEN):
  the SDK builds the POLY_1271 **order** signature correctly but its **L1 auth**
  binds the API key to the EOA (`create_level_1_headers` / `sign_clob_auth_message`
  use `signer.address()` + plain ECDSA), so orders are rejected with
  `the order signer address has to be the address of the API KEY`.

The fix mirrors the SDK's own order-signature wrapper for the `ClobAuth` message:
`POLY_ADDRESS = deposit_wallet`, and an ERC-7739 / Solady `TypedDataSign`
signature over the `ClobAuth` contents under the `DepositWallet` domain, signed by
the EOA key — reusing the SDK's exact `DEPOSIT_WALLET_*` constants so it cannot
drift from the order path.

## 2. Current system architecture

```
get_clob_client (USE_CLOB_V2)  ->  ClobV2Client._build_client
  ClobClient(key=EOA, signature_type, funder=deposit_wallet, builder_config)
  if signature_type == 3 (POLY_1271):
     client.signer.address = lambda: deposit_wallet      # L2 header POLY_ADDRESS
     creds = derive_or_create_deposit_wallet_creds(...)  # corrected L1 auth
     client.set_api_creds(creds)
  else:
     client.set_api_creds(client.create_or_derive_api_key())   # unchanged

deposit_wallet_auth.build_poly_1271_clob_auth_signature(...)   # pure, unit-tested
  contents_hash      = keccak(CLOBAUTH_TYPE_HASH + deposit_wallet + ts + nonce + msg)
  tds_struct_hash    = keccak(SOLADY_AUTH_TYPE_HASH + contents_hash
                              + DEPOSIT_WALLET_NAME/VERSION_HASH + chainId
                              + deposit_wallet + DEPOSIT_WALLET_DOMAIN_SALT)
  digest             = keccak(0x1901 + ClobAuthDomain_separator + tds_struct_hash)
  envelope           = 0x + ECDSA(digest, EOA) + domainSep + contentsHash
                            + contentsTypeString + uint16(len)
```

`ClobAuth` type string, struct hash, and the 3-field `ClobAuthDomain` separator
are pinned byte-exact against `poly_eip712_structs` in the unit test, so the
contents/domain hashing matches what the server computes.

Order signing itself is the SDK's existing POLY_1271 path (maker == signer ==
deposit wallet, ERC-7739 wrapped) — unchanged.

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/integrations/clob/deposit_wallet_auth.py` — corrected POLY_1271 L1 auth + `derive_or_create_deposit_wallet_creds`.
- `projects/polymarket/crusaderbot/tests/test_deposit_wallet_1271_auth.py` — 7 tests (encoding parity vs the SDK/poly_eip712_structs, envelope byte-layout, determinism, POLY_ADDRESS-binds-to-deposit-wallet).
- `projects/polymarket/crusaderbot/reports/forge/deposit-wallet-1271-auth.md` (this file).

Modified:
- `projects/polymarket/crusaderbot/integrations/clob/v2_client.py` — `_POLY_1271_SIGNATURE_TYPE`; sig-type-3 branch in `_build_client` (bind L2 POLY_ADDRESS to the deposit wallet; derive creds via the corrected path).
- `.github/workflows/staging-proof-fly.yml` — `git_ref` (clone+test a branch without merging to main), `funder_override` (pass the deposit wallet as maker), `signature_type='3'` option; `GIT_REF` plumbed into the in-machine clone (`--branch`) + env-forward list; funder override threads into `STAGING_FUNDER_ADDRESS`.
- `projects/polymarket/crusaderbot/tests/staging/test_live_reconcile_staging.py` — pre-order DIAG line (signer EOA / funder / sig type) printed BEFORE `post_order` so addresses are visible even when the order rejects.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `state/CHANGELOG.md` — updated.

## 4. What is working

- 7 new unit tests pass; `ruff` clean on all touched files; the v2_client imports
  and lints clean.
- The wrapper is verified deterministic and structurally correct (202-byte
  envelope = 65 inner sig + 32 domain sep + 32 contents hash + the ClobAuth type
  string + 2-byte length), and its `ClobAuth` contents hash + `ClobAuthDomain`
  separator equal `poly_eip712_structs`' own outputs byte-for-byte.
- Zero behaviour change for every non-POLY_1271 wallet — the sig-type-3 branch is
  the only new path; EOA/POLY_PROXY/GNOSIS_SAFE keep the SDK's native derive.
- The staging workflow can now clone+run a WARP branch (`git_ref`) and pass the
  deposit wallet as maker (`funder_override`) with `signature_type='3'`, so the
  fix is validated on the real broker (`allow_fills=false`) before any merge.

## 5. Known issues

- **Server-side L1 verification encoding is not publicly documented.** Upstream
  issue #70 is OPEN with no maintainer fix, so the wrapped-auth format here is a
  best-effort reconstruction from the SDK's order wrapper + the issue's described
  fix. The **live staging proof is the arbiter** — if it still rejects, the
  encoding (e.g. the verifier domain choice) needs adjustment, or the L2 header /
  request path needs the same deposit-wallet binding.
- **Durable fallback if the Python path can't be made to work:** adopt
  Polymarket's Rust SDK (`rs-clob-client-v2` / `polymarket_client_sdk_v2`), which
  the ecosystem reports as the only client currently trading deposit wallets — a
  larger execution-backend lane, owner-gated.
- **Broker validation result (2026-06-09, real CLOB, allow_fills=false):** the
  error moved forward each iteration but did NOT reach green:
  - baseline (sig 1/2, legacy proxy maker): `400 maker address not allowed`.
  - iter 1 (sig 3, deposit-wallet maker; harness still fed EOA-bound creds):
    `401 Unauthorized/Invalid api key` — **the maker-not-allowed blocker is GONE**
    (sig 3 + deposit wallet is accepted as a maker).
  - iter 2 (sig 3 + `ensure_clob_credentials` routed through the deposit-wallet
    derive — my L1 auth actually exercised): `401 Invalid L1 Request headers` on
    both `/auth/derive-api-key` and `/auth/api-key`.
  So the diagnosis + maker path are proven; the wall is the exact ERC-7739 L1
  encoding, which Polymarket's server rejects. My encoding matches the
  publicly-described spec, but **no public working byte-level implementation
  exists** (upstream issues #64/#65/#70 all OPEN) — the remaining unknowns are in
  Polymarket's closed server-side verification. Further blind iteration is
  low-EV; stopped here.
- **Go-live remains owner-gated.** Even a green order-placement proof does not
  flip `ENABLE_LIVE_TRADING` or run a real-money fill; those are owner decisions.

## 6. What is next

- DECISION (owner): pick the path now that the Python deposit-wallet L1 encoding
  is blocked on Polymarket's undocumented server verification:
  1. **Trade now on a non-migrated wallet** — a Polymarket account still on the
     legacy POLY_PROXY system trades today with sig type 1 (the bot's existing,
     WARP-74-proven path). The owner's current account is migrated → blocked on
     this lane.
  2. **Durable deposit-wallet support** — adopt Polymarket's Rust SDK
     (`polymarket-client-sdk-v2` / `rs-clob-client-v2`, the only client the
     ecosystem reports trading deposit wallets) as the order backend via a Rust
     sidecar invoked from the Python bot. Scoped lane, owner-gated.
  3. **Wait + complete this PR** — the moment Polymarket publishes/fixes the L1
     deposit-wallet encoding, this PR finishes (the wrapper + wiring + proof
     scaffolding are in place; only the byte layout needs the spec).
- This PR stays OPEN (documented WIP), gated to sig type 3 only (no effect on the
  active sig-1/2 paths). NOT merged — the broker does not yet accept the auth.
- OWNER (separate, gated): the live cutover — `ENABLE_LIVE_TRADING` +
  `allow_fills` + a small real-money fill test — stays an owner decision.
