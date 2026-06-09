# WARP•R00T Report — deposit-wallet-autoderive

- Validation Tier: MAJOR (CLOB order maker/funder resolution)
- Claim Level: NARROW INTEGRATION (auto-resolves the deposit-wallet funder via the already-merged AsyncSecureClient path; no new order or auth logic)
- Validation Target: `ensure_clob_credentials` POLY_1271 branch (caches the SDK-resolved wallet), the new `effective_funder` resolver, and its wiring into `get_clob_client`'s client constructors.
- Not in Scope: per-user on-chain trading (the live order path is single-key by design — `get_clob_client(s)` uses `POLYMARKET_PRIVATE_KEY`); the live broker green proof (waits on the wallet being funded); enabling `USE_CLOB_V2` in prod (operator-gated).
- Suggested Next Step: operator funds the deposit wallet (≥ ~$1.50 USDC), runs the staging proof WITHOUT `funder_override` to confirm auto-derive end-to-end, then enables `USE_REAL_CLOB` + `USE_CLOB_V2` + sig type 3 (live still owner-gated).

---

## 1. What was built

Turnkey deposit-wallet trading: the operator no longer has to look up and hardcode
`POLYMARKET_FUNDER_ADDRESS`. For signature type 3 (POLY_1271 deposit wallets),
the configured signer key alone is enough — the bot resolves the signer's current
deterministic deposit wallet via the official `polymarket` SDK's
`AsyncSecureClient` and uses it as the order maker/funder.

This follows the merged `deposit-wallet-1271-auth` lane (PR #1727), which proved
deposit-wallet order placement on the real broker. That lane still required the
correct funder address to be supplied; this lane removes that manual step.

## 2. Current system architecture

```
ensure_clob_credentials(settings)            # once at startup
  if sig_type == 3 (POLY_1271):
     sc = await AsyncSecureClient.create(
              private_key=KEY,
              wallet=POLYMARKET_FUNDER_ADDRESS or None)   # None → SDK auto-derives
     _derived        = sc.credentials   # deposit-wallet L2 creds
     _derived_wallet = sc.wallet        # the resolved deterministic deposit wallet

effective_funder(settings)
  sig_type == 3 and _derived_wallet  ->  _derived_wallet     # SDK-resolved wins
  else                               ->  POLYMARKET_FUNDER_ADDRESS

get_clob_client(settings)
  ClobV2Client(..., funder_address=effective_funder(s), ...)  # maker = resolved wallet
```

The SDK's `AsyncSecureClient.create(wallet=None)` runs an on-chain factory check
to pick the *current* deterministic deposit wallet (beacon vs UUPS), so this is
correct across Polymarket's wallet generations without us re-deriving addresses.
When a funder IS configured, it is forwarded to the SDK for validation and the
SDK-resolved wallet remains the authoritative cache.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/integrations/clob/__init__.py` — new
  `_derived_wallet` cache; POLY_1271 branch of `ensure_clob_credentials` now
  resolves + caches the SDK wallet (funder optional, `wallet=funder or None`);
  new `effective_funder` resolver; all `get_clob_client` client constructors use
  `effective_funder(s)`.

Created:
- `projects/polymarket/crusaderbot/tests/test_deposit_wallet_autoderive.py` — 5
  tests (mocked AsyncSecureClient): auto-derive when funder unset, configured
  funder forwarded, `effective_funder` precedence for sig 3 + non-sig-3, and the
  v2 client built with the resolved funder.

Report / state:
- `projects/polymarket/crusaderbot/reports/forge/deposit-wallet-autoderive.md`,
  `state/PROJECT_STATE.md`, `state/CHANGELOG.md`.

## 4. What is working

- 5 new tests pass; 233 clob/pysdk/v2/deposit-wallet regression tests pass; `ruff`
  clean.
- Auto-derive is gated to sig type 3: `effective_funder` returns the env funder
  unchanged for EOA/POLY_PROXY/GNOSIS_SAFE, so those paths are byte-identical.
- Default-off preserved: `USE_REAL_CLOB` / `USE_CLOB_V2` stay `False`;
  `ENABLE_LIVE_TRADING` untouched. No runtime change until the operator opts in.

## 5. Known issues

- **Ordering contract.** `effective_funder` reads `_derived_wallet`, which is
  populated by `ensure_clob_credentials` — which must run (once, at startup)
  before `get_clob_client` for sig 3. This matches the existing `_derived`
  credential-cache contract; a sig-3 `get_clob_client` call before startup
  derivation would fall back to the env funder (None if unset).
- **Not yet broker-proven end-to-end** — the SDK call is mocked in tests; the live
  auto-derive run is deferred until the wallet is funded (PR #1727 already proved
  the order path itself on the real broker).
- **Single-key execution.** The live order path trades from one configured wallet
  by design; true per-user on-chain CLOB trading is a separate architecture lane,
  not in scope.

## 6. What is next

- Operator: fund the deposit wallet, dispatch the staging proof with
  `funder_override` BLANK (proves auto-derive), expect a green case3.
- Then operator enables `USE_REAL_CLOB` + `USE_CLOB_V2` + sig type 3 in Fly;
  owner flips `ENABLE_LIVE_TRADING` when ready (still owner-gated).
- Cleanup follow-up: remove the now-unused `deposit_wallet_auth.py` wrapper
  (superseded by AsyncSecureClient).
