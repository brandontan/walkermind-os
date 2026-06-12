# builder-key-preference — SDK gasless key selection: Builder first

Branch: `WARP/root-builder-key-preference`
Role: WARP•R00T
Date: 2026-06-12 (Asia/Jakarta)

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: `sdk_api_key()` credential preference in
`projects/polymarket/crusaderbot/integrations/clob/sdk_env.py` and its three
preference tests.
Not in Scope: AsyncSecureClient call sites (unchanged), builder_relayer
integration (reads POLY_BUILDER_* directly, untouched), config aliasing
(`_alias_poly_builder_creds` already maps POLYMARKET_BUILDER_* → POLY_BUILDER_*
on main), PR #1777 disposition (separate decision).

## 1. What was built

Flipped the gasless API-key preference in `sdk_api_key()` from
`RelayerApiKey > BuilderApiKey` to `BuilderApiKey > RelayerApiKey`.

Root cause (prod, 2026-06-12 09:20 UTC backfill re-tap): the relayer key is
address-BOUND — the relayer rejects any request whose `from` differs from the
key's own address. All 6 deposit-wallet resolves failed with
`from 0x<user EOA> does not match auth 0x<relayer address>` because the
relayer key (both RELAYER_API_KEY and RELAYER_API_KEY_ADDRESS set in Fly) won
the preference over the builder credential set. A BuilderApiKey relays on
behalf of ARBITRARY user EOAs (builder pays gas) — the only key kind that can
deploy deposit wallets for our per-user HD addresses.

Gemini #1778 applied (adapted): a half-configured credential family now emits
ONE deduped WARNING per process (field names only, never values) and keeps the
safe fallback — Gemini proposed raising, rejected because `sdk_api_key()` runs
on every client build including already-deployed-wallet resolves that need no
key; a raise would convert a config smell into a capital-path outage.

## 2. Current system architecture

Unchanged. `sdk_api_key()` remains the single choke point feeding `api_key=`
to every `AsyncSecureClient.create` call (AST-pinned by
`tests/test_sdk_rpc_pin.py`). Selection order is now:

1. `BuilderApiKey(POLY_BUILDER_API_KEY/SECRET/PASSPHRASE)` — populated in prod
   via the `_alias_poly_builder_creds` validator from the operator's
   POLYMARKET_BUILDER_* Fly secrets.
2. `RelayerApiKey(RELAYER_API_KEY, RELAYER_API_KEY_ADDRESS)` — fallback,
   valid only for the key's own address.
3. `None` — already-deployed wallets still resolve.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/integrations/clob/sdk_env.py` — preference
  flip + docstring records the prod evidence.
- `projects/polymarket/crusaderbot/tests/test_gasless_custody.py` —
  `test_sdk_api_key_prefers_builder_key` (both sets present → Builder),
  `test_sdk_api_key_falls_back_to_relayer` (builder absent → Relayer);
  unconfigured → None unchanged.
- `projects/polymarket/crusaderbot/reports/forge/builder-key-preference.md` —
  this report.

## 4. What is working

- `pytest tests/test_gasless_custody.py tests/test_sdk_rpc_pin.py` — 18/18
  pass (preference triple + AST source pin + kwarg passthrough).
- Builder creds are confirmed present in Fly
  (POLYMARKET_BUILDER_API_KEY/_API_SECRET/_PASSPHRASE secret names listed) and
  alias into POLY_BUILDER_* at settings load.

## 5. Known issues

- The builder credential set has not yet been exercised end-to-end against the
  relayer service from prod — if the builder key is invalid/expired the
  backfill will fail with a service auth error (visible in
  `backfill_deposit_wallet_failed` log lines, secrets redacted).

## 6. What is next

Merge → Fly CD deploy → owner re-taps Admin → "Backfill deposit wallets" →
expect `scanned=6 filled=6`; verify `wallets.polymarket_deposit_wallet`
6/6 in Supabase.

Suggested Next Step: after backfill fills 6/6, make deposit-wallet resolve
automatic at wallet creation (owner directive: no manual checking).
