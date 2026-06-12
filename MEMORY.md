#CrusaderBot — WALKERMIND OS

## UI Standards
- **Branding:** ❧𝗖𝗥𝗨𝗦𝗔𝗗𝗘𝗥 | 𝗔𝗨𝗧𝗢𝗕𝗢𝗧
- **Language:** English-only (US).
- **Terminal HUD:** Use <pre> blocks for monospaced financial data.
- **Dividers:** Use heavy box characters (━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
).
- **Width:** 40+-character headers for full-width mobile bubbles.

## Runtime Pipeline
- **Scanner:** Log candidate counts to process_metadata.
- **Analyzer:** Generate 'reasoning' string for every SignalCandidate.
- **Execution: **Push Realtime Events via SSE.

## Role Model
- **Admin:** ROOT_ADMIN_ID or 'ADMIN' tier in db.
- **User:** Any registered user; no tier gates.
---

## Polymarket Integration Memory Lock

Last Reviewed: 2026-06-13 05:07 Asia/Jakarta
Source: Official Polymarket documentation at https://docs.polymarket.com/ and https://docs.polymarket.com/api-reference/introduction

Authority note:
- This file is persistent implementation memory only.
- AGENTS.md, PROJECT_REGISTRY.md, project state files, current code truth, and live official docs still win.
- Re-read the official docs before coding against external API behavior because Polymarket docs/API contracts may change.
- Never store secrets, API keys, private keys, signatures, passphrases, or secret-derived values in this file, reports, PR bodies, logs, or test fixtures.

### API Boundaries

Polymarket has separate API domains. Do not mix their responsibilities.

- Gamma API: `https://gamma-api.polymarket.com`
  - Markets, events, tags, series, comments, sports, search, public profiles.
  - Primary discovery/browsing API for public market data.
- Data API: `https://data-api.polymarket.com`
  - User positions, trades, activity, holder/open-interest data, leaderboards, builder analytics.
- CLOB API: `https://clob.polymarket.com`
  - Orderbook data, pricing, midpoints, spreads, price history.
  - Also handles order placement, cancellation, and other trading operations.
  - Public read endpoints exist; trading/order-management endpoints require CLOB authentication.
- Bridge API: `https://bridge.polymarket.com`
  - Deposits and withdrawals.
  - Official docs state Bridge is a proxy of the fun.xyz service.
- Relayer API: `https://relayer-v2.polymarket.com`
  - Gasless wallet/on-chain transactions.
  - Wallet deployment, approvals, CTF operations, transfers, transaction status/nonce/deployed checks.

### Authentication Boundaries

CLOB auth, Builder attribution, Builder API keys, and Relayer API keys are different concepts.

CLOB:
- CLOB uses two auth levels:
  - L1 private-key/EIP-712 proof for creating or deriving API credentials and locally signing orders.
  - L2 API credentials (`apiKey`, `secret`, `passphrase`) for authenticated CLOB requests.
- Authenticated CLOB trading endpoints require the five `POLY_*` L2 HTTP headers.
- Even with L2 headers, order creation still requires a signed order payload.
- Do not confuse CLOB L2 credentials with Relayer/Builder credentials.

Builder Code:
- Builder Code is a public `bytes32` identifier for order attribution.
- It is attached to order structs, appears in the order `builder` field, and does not replace authentication.
- Store only the public builder code in env/config. It is not a secret, but still keep config scoped.

Builder Program / Relayer:
- A builder routes user orders through Polymarket.
- Builder benefits include relayer access for gasless on-chain operations and order attribution.
- EOA wallets do not have relayer access; users trading directly from EOAs pay their own gas.
- New API users should use deposit wallets.
- Builder Relayer Client is used for deposit wallet deployment and signed wallet batches.
- CLOB client is still used for CLOB order signing/posting/canceling/balances/account data.

Relayer API Key:
- Relayer auth can use Relayer API key headers:
  - `RELAYER_API_KEY`
  - `RELAYER_API_KEY_ADDRESS`
- Builder API key auth can use:
  - `POLY_BUILDER_API_KEY`
  - `POLY_BUILDER_TIMESTAMP`
  - `POLY_BUILDER_PASSPHRASE`
  - `POLY_BUILDER_SIGNATURE`
- `RELAYER_API_KEY_ADDRESS` must match the address that owns the relayer key.
- Relayer API keys are not CLOB API keys.

### Deposit Wallet Truth

Deposit wallet is the path for new API users.

Core model:
- Deposit wallet is a per-user ERC-1967 proxy.
- It holds pUSD and conditional tokens on-chain.
- It has two different signing paths:
  1. Deposit-wallet batch for on-chain wallet calls, submitted to relayer as a `WALLET` transaction.
  2. CLOB order with `signatureType = 3` / `POLY_1271`, validated through ERC-1271.
- These signatures are not interchangeable.

Deployment:
- Deploy via relayer `WALLET-CREATE`.
- The request needs owner/signer address and deposit wallet factory target.
- SDKs can derive deterministic deposit wallet addresses.
- Treat relayer submit as async: submit returns transaction id/state first, then poll until confirmed.
- Do not treat wallet ready solely because an address can be derived.

Trading from deposit wallet:
- Deposit wallet must be funded with pUSD.
- pUSD held by the owner EOA does not count as CLOB buying power for deposit wallet orders.
- Approvals must be made from the deposit wallet, not from the owner EOA.
- After funding/changing allowances, call CLOB balance allowance update with `signature_type = 3`.
- CLOB client for deposit wallet orders must use:
  - `signatureType = 3` / `POLY_1271`
  - deposit wallet as funder
  - maker = deposit wallet
  - signer = deposit wallet
- CLOB order payload still needs signing.

### pUSD / Collateral Truth

- pUSD is the collateral token used for all trading on Polymarket.
- pUSD is an ERC-20 token on Polygon mainnet.
- Decimals: 6.
- It is backed by USDC and represents a USDC claim.
- Polymarket protocol settlement is in native USDC; pUSD is the wrapper/collateral layer used inside the platform.
- pUSD is the target tradeable balance.
- Native USDC or USDT deposits must not be credited as available trading balance until docs-aligned settlement into pUSD/tradeable balance is complete.

USDC.e onramp/offramp:
- USDC.e wraps to pUSD through `CollateralOnramp.wrap`.
- `_asset` for wrap must be USDC.e.
- Amount is in USDC.e base units with 6 decimals.
- Caller must approve the CollateralOnramp contract to spend USDC.e before wrapping.
- Unwrap pUSD to USDC.e through `CollateralOfframp.unwrap`.
- `_asset` for unwrap must be USDC.e.

### Bridge API Truth

Bridge is the first-line path for USDC/USDT deposit enablement. Do not default to custom DEX/swap logic.

Supported assets:
- `GET /supported-assets`
- Returns supported asset objects with:
  - `chainId`
  - `chainName`
  - token `name`
  - token `symbol`
  - token `address`
  - token `decimals`
  - `minCheckoutUsd`
- Capability truth for user-facing enablement must come from this endpoint plus local backend support.
- Fail closed if Bridge is down, stale, or unsupported for the requested token/network.

Create bridge deposit address:
- `POST /deposit`
- Body uses the Polymarket wallet address where funds should be credited as pUSD.
- Response may return addresses such as:
  - `evm`
  - `svm`
  - `btc`
- Docs note: only certain chains/tokens are supported; use `/supported-assets`.
- Do not display QR/address/copy for unsupported token/network pairs.
- COPY remains raw address only.

Quote:
- `POST /quote`
- Required body includes:
  - `fromAmountBaseUnit`
  - `fromChainId`
  - `fromTokenAddress`
  - `recipientAddress`
  - `toChainId`
  - `toTokenAddress`
- Response includes quote/output/fee/impact fields such as:
  - `estCheckoutTimeMs`
  - `estFeeBreakdown`
  - `minReceived`
  - `estInputUsd`
  - `estOutputUsd`
  - `estToTokenBaseUnit`
  - `quoteId`
- Use base units and token decimals correctly.
- Quote output is estimate; do not credit available balance from quote alone.

Status:
- `GET /status/{address}`
- Returns transaction records with:
  - `fromChainId`
  - `fromTokenAddress`
  - `fromAmountBaseUnit`
  - `toChainId`
  - `toTokenAddress`
  - `createdTimeMs`
  - `status`
  - `txHash` when available
- Example statuses include:
  - `DEPOSIT_DETECTED`
  - `PROCESSING`
  - `COMPLETED`
- Only completed/tradeable settlement may increase live available balance.

Withdraw:
- Bridge has a withdrawal-address endpoint for selected destination chain/token/recipient.
- If withdrawal flow is touched, web notification must reflect actual confirmed/completed status, not request/submission.

### Relayer API Truth

Submit:
- `POST /submit`
- Authenticated using Builder API Key headers or Relayer API Key headers.
- Submit returns immediately with:
  - `transactionID`
  - state such as `STATE_NEW`
- It does not return on-chain tx hash at submission time.
- Poll `GET /transaction?id=...` to retrieve `transactionHash` once broadcast/confirmed.

Transaction lookup:
- `GET /transaction`
- Query by transaction id.
- Response can include:
  - `transactionID`
  - `transactionHash`
  - `from`
  - `to`
  - `proxyAddress`
  - `nonce`
  - `state`
  - `type`
  - `owner`
  - timestamps
- Do not mark relayer work complete from submit alone.

Recent transactions:
- `GET /transactions`
- Returns recent relayer transactions for a user.
- Authenticated with Builder API Key or Relayer API Key headers.

Nonce:
- `GET /nonce`
- Docs describe current Proxy/Safe nonce for a user.
- Query params include signer `address` and nonce `type`.
- Listed types include `PROXY` and `SAFE`.
- Deposit wallet docs/SDK flows may handle `WALLET` nonce internally for deposit-wallet batches; do not invent raw `WALLET` API behavior without code/docs proof.

Wallet deployed:
- `GET /deployed`
- Can check deployed wallet state.
- Be careful with readiness: deployed/address existence is not the same as all approvals/balance/registry state being ready for CLOB trading.

### CrusaderBot Implementation Posture

For deposit enablement:
- Polygon-only unless a new lane explicitly enables other networks.
- User-facing token enabled means backend can process it end-to-end:
  - supported-assets truth
  - address/QR/copy
  - detection/status
  - quote/settlement tracking where needed
  - pUSD/tradeable settlement
  - ledger credit
  - reconciliation
  - reorg/failure handling
  - audit trail
  - web notification
- Native Polygon USDC and Polygon USDT must not become live available balance until completed Bridge/pUSD/tradeable settlement is proven.
- Pending/detected/processing deposits do not count toward:
  - live available balance
  - $5 Auto-Trade gate
  - order sizing
- Failed/expired/manual-review deposits do not count.
- Preserve original audit truth:
  - original token symbol
  - original token address
  - network/chain id
  - tx hash
  - raw base-unit amount
  - decimals
  - normalized/tradeable credit amount
  - status transitions
- Reorg/revert must debit exactly the normalized amount previously credited.
- Wrong/unsupported token deposits remain credit-neutral and operator-visible.

For withdrawal:
- Web notification required on confirmed/completed withdrawal.
- Telegram notification can coexist but must not be the only channel.
- Deduplicate notifications by withdrawal id / tx hash / status transition.

For web notifications:
- Deposit confirmed/completed and credited => persisted web/in-app notification.
- Withdrawal confirmed/completed => persisted web/in-app notification.
- Do not notify “confirmed” for detected/processing/submitted states.
- Unread counters must update correctly.
- Paper/live notification isolation remains mandatory.

For testing:
- No real fund movement in tests.
- No real external Bridge/Relayer/CLOB calls in CI.
- Mock supported-assets, deposit, quote, status, withdraw, and relayer responses.
- No secrets in fixtures/logs/reports.

Hard no:
- Do not implement custom DEX/swap routing unless official Bridge cannot cover the target and WARP CMD approves a separate expansion.
- Do not flip `USE_REAL_CLOB`, `EXECUTION_PATH_VALIDATED`, `ENABLE_LIVE_TRADING`, or `CAPITAL_MODE_CONFIRMED` as part of deposit/bridge work.
- Do not treat report claims as proof; code truth wins.
