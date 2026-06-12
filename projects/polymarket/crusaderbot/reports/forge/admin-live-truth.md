# admin-live-truth — admin mode-scoping + SDK gasless api_key wiring

Role: WARP•R00T (owner reports w/ screenshots 2026-06-12 11:51 WIB)
Branch: WARP/root-admin-live-truth
Date: 2026-06-12 12:35 Asia/Jakarta

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : /admin/users mode-scoped roster; AdminPage backfill rendering; sdk_api_key wiring into every AsyncSecureClient build
Not in Scope      : custody transfer internals, order execution, risk constants, guards
Suggested Next    : merge on CI green -> deploy -> owner re-taps Backfill (expect deposit wallets filled 6/6)

## 1. What was built
Owner armed the custody flags (verified: restart + safes backfill FILLED 6/6 in prod
DB — gasless custody live at the address layer; /wallet now shows the Safe). Three
fixes from the same session evidence:
1. /admin/users roster showed LIVE mode with the PAPER/mixed balance — per-row
   mode scoping (live -> real-money ledger bucket; paper -> mixed − live; open
   positions filtered to the row's mode).
2. The Backfill button rendered only the deposit-wallet summary — AdminPage now
   shows the Safes summary too (api.ts response type widened).
3. Deposit-wallet resolve still skipped 6/6: REPRODUCED with a throwaway key —
   the SDK raises UserInputError "Gasless transactions require a Builder API Key
   or Relayer API Key" when resolving/deploying a deposit wallet for a fresh
   EOA. The owner's RELAYER_API_KEY + RELAYER_API_KEY_ADDRESS secrets map 1:1
   onto polymarket.auth.RelayerApiKey and were never referenced in code. Fixed:
   config fields + sdk_env.sdk_api_key() (RelayerApiKey > BuilderApiKey > None,
   stub-tolerant) threaded as api_key= into ALL FOUR AsyncSecureClient builds;
   the AST source-pin now requires BOTH environment= and api_key= on every
   create call.

## 2. Current system architecture (relevant slice)
AsyncSecureClient.create(..., environment=production_environment(), api_key=sdk_api_key())
  api_key: RelayerApiKey(RELAYER_API_KEY, RELAYER_API_KEY_ADDRESS)  [preferred]
           | BuilderApiKey(POLY_BUILDER_*)                          [fallback]
           | None (resolves only already-deployed wallets)
/admin/users: balance + open positions scoped by each row's trading_mode.

## 3. Files created / modified
- projects/polymarket/crusaderbot/config.py — RELAYER_API_KEY / RELAYER_API_KEY_ADDRESS fields
- projects/polymarket/crusaderbot/integrations/clob/sdk_env.py — sdk_api_key()
- projects/polymarket/crusaderbot/integrations/clob/user_client.py / __init__.py / sdk_client.py — api_key= wired
- projects/polymarket/crusaderbot/webtrader/backend/router.py — /admin/users mode-scoped
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AdminPage.tsx + lib/api.ts — safes summary rendering
- projects/polymarket/crusaderbot/tests/test_gasless_custody.py (+3) / test_sdk_rpc_pin.py (pin extended)

## 4. What is working
FULL SUITE 3474 passed / 11 skipped (+3); ruff clean; tsc + vite build clean.
Prod-verified this session: safes 6/6 filled; custody flags armed by owner.

## 5. Known issues
- Deposit-wallet fill 6/6 expected only after deploy + owner re-tap (the wired
  key must reach the runtime).
- Admin overview aggregate "WALLETS USDC" remains the mixed custody total by
  design (pool-level stat).

## 6. What is next
Merge -> deploy -> owner re-taps Backfill -> verify polymarket_deposit_wallet
filled 6/6 -> per-user live execution funder column complete.
