# sdk-rpc-pin — polymarket SDK chain reads pinned to operator RPC

Role: WARP•R00T (owner-assigned live-readiness program 2026-06-11)
Branch: WARP/root-sdk-rpc-pin
Date: 2026-06-11 22:55 Asia/Jakarta

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : every AsyncSecureClient build in integrations/clob (backfill resolve, per-user creds resolve, global creds derive, pysdk order client)
Not in Scope      : order submit logic, risk constants, guards, kill switch, strategy, migrations, the SDK itself
Suggested Next    : WARP•R00T merge on CI green -> CD deploy -> owner re-taps Admin 'Backfill deposit wallets' (expect filled 6)

## 1. What was built

ROOT CAUSE of the admin backfill failure (owner screenshot 2026-06-11 22:21 WIB:
"Done — scanned 6, filled 0, skipped 6"): the official polymarket SDK ships
`PRODUCTION.rpc_url = "https://polygon.drpc.org"` (environments.py:75) and uses
it for the on-chain deposit-wallet factory check inside
`AsyncSecureClient.create`. None of our call sites overrode `environment=`, so
every resolve rode a free third-party endpoint that throttles/fails from the
Fly machine — all 6 resolves failed identically while our configured
POLYGON_RPC_URL was healthy. The same hidden dependency sat under the per-user
live order path and the global creds derive — a third-party SPOF on the
capital path.

FIX: new `integrations/clob/sdk_env.production_environment()` —
`dataclasses.replace(PRODUCTION, rpc_url=get_settings().POLYGON_RPC_URL)`
(import deferred; SDK-less environments unaffected). Wired as `environment=`
into ALL FOUR AsyncSecureClient builds:
- `integrations/clob/user_client.resolve_deposit_wallet` (the backfill path)
- `integrations/clob/user_client.resolve_deposit_wallet_creds` (per-user live)
- `integrations/clob/__init__.ensure_clob_credentials` (global sig-3 derive)
- `integrations/clob/sdk_client.PySdkClobClient._ensure_client` (pysdk orders)

Only `rpc_url` changes — every Polymarket service URL and wallet-derivation
constant stays byte-identical to the SDK's own PRODUCTION values
(pinned by test).

## 2. Current system architecture (relevant slice)

```
AsyncSecureClient.create(..., environment=production_environment())
                                |- PRODUCTION (SDK constants, untouched)
                                '- rpc_url := settings.POLYGON_RPC_URL
on-chain factory check (beacon vs UUPS deposit wallet) -> operator RPC
```

## 3. Files created / modified

- projects/polymarket/crusaderbot/integrations/clob/sdk_env.py — new helper
- projects/polymarket/crusaderbot/integrations/clob/user_client.py — both resolve fns pass pinned environment
- projects/polymarket/crusaderbot/integrations/clob/__init__.py — ensure_clob_credentials passes pinned environment
- projects/polymarket/crusaderbot/integrations/clob/sdk_client.py — order client build passes pinned environment
- projects/polymarket/crusaderbot/tests/test_sdk_rpc_pin.py — new (helper unit pin vs real SDK constants, source pin over every create call, backfill-path kwarg capture)
- projects/polymarket/crusaderbot/tests/test_user_clob_client.py / test_deposit_wallet_autoderive.py — fixtures feed sdk_env hermetic settings
- projects/polymarket/crusaderbot/reports/forge/sdk-rpc-pin.md + state files

## 4. What is working

- 68/68 touched-surface tests green (sdk_rpc_pin, user_clob_client, deposit_wallet_autoderive, clob_pysdk, deposit_wallet_persist, live_per_user_wiring); ruff clean; full suite in CI.
- Source pin guards future call sites: any new `AsyncSecureClient.create(` in integrations/clob without the pinned environment fails CI.

Session context (same day, prior lane): deposit pipeline proven END-TO-END on
mainnet — owner's $1 USDC.e test (block 88,324,342) seen, recorded and
CONFIRMED by the watcher at 15:28:55 UTC after an evidence-backed cursor jump
(on-chain proof: zero transfers to any watched address in the skipped range —
the $1 was the only erc20 transfer to any of the 6 addresses, ever). Gate 4
for walk3r69 now reads 1 confirmed deposit.

## 5. Known issues

- The backfill retry (owner button re-tap) needs this lane DEPLOYED first.
- Catch-up throttling observation (resolved): Alchemy Free flapped 429s during the chunked catch-up burst; absorbed by retries, stopped once the cursor reached head after the jump.

## 6. What is next

1. Merge on CI green (WARP•R00T full-bypass) -> CD deploy.
2. Owner: re-tap WebTrader Admin -> 'Backfill deposit wallets' — expect `filled 6`.
3. Per-user live execution then has its identity column populated; the 8-gate /enable_live opt-in is the remaining owner step (plus Alchemy key rotation, still recommended).
