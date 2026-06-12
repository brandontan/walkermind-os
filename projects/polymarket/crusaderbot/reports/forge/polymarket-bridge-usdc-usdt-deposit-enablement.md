# #1805 — polymarket-bridge-usdc-usdt-deposit-enablement

**Project:** CrusaderBot (`projects/polymarket/crusaderbot`)  
**Role:** WARP•FORGE  
**Branch:** `WARP/polymarket-bridge-usdc-usdt-deposit-enablement`  
**Validation Tier:** MAJOR  
**Claim Level:** NARROW INTEGRATION  
**Last Updated:** 2026-06-13 05:26 Asia/Jakarta

## Verdict

FORGE build is complete for a docs-aligned Polymarket Bridge / pUSD foundation, but **Polygon native USDC and Polygon USDT remain user-facing DISABLED**.

Reason: the current repo still has no scheduled Bridge deposit-address/status poller that can turn terminal Bridge `COMPLETED` records into credited live balance. Enabling the UI token before that active settlement loop exists would fake-enable deposits. This lane therefore adds the adapter, schema substrate, and notification safety pieces needed for the next gate while preserving the existing USDC.e-only enabled path.

## Polymarket docs/API reviewed in-run

Official docs reviewed during this run:

- API Introduction — Bridge API is separate from Gamma/Data/CLOB and served at `https://bridge.polymarket.com`.
- Bridge `GET /supported-assets` — returns chain/token/minimum fields.
- Bridge `POST /deposit` — returns bridge deposit addresses and credits the supplied Polymarket wallet address as pUSD.
- Bridge `POST /quote` — accepts source token/chain/base units and targets Polygon pUSD.
- Bridge `GET /status/{address}` — returns status records including non-terminal and terminal states.
- pUSD concept page — pUSD is Polygon ERC-20 collateral; USDC.e wraps through CollateralOnramp; Bridge deposits can auto-wrap to pUSD.
- Deposit Wallets — wallet actions must wait for confirmed relayer state before relying on effects.

Live non-secret API probe:

```text
curl -fsSL -A 'Mozilla/5.0' https://bridge.polymarket.com/supported-assets
```

Observed Polygon Bridge-advertised assets include:

| Asset | Address | Status in CrusaderBot |
|---|---|---|
| USDC.e | `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` | ENABLED existing raw USDC.e path |
| Native USDC | `0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359` | Bridge-supported, UI/API disabled until active status settlement |
| USDT | `0x9417669fBF23357D2774e9D421307bd5eA1006d2` | Bridge-supported, UI/API disabled until active status settlement |
| pUSD | `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB` | Required terminal settlement target |

## Implementation

### Bridge adapter

Added `projects/polymarket/crusaderbot/integrations/polymarket_bridge.py`:

- Parses `supportedAssets` into typed `BridgeAsset` records.
- Parses bridge deposit-address responses into raw `evm/svm/btc/tvm` fields.
- Builds quote requests targeting Polygon pUSD by default.
- Parses status records into `BridgeTransaction` records.
- Exposes `completed_pusd_settlements()` so crediting code has one clear terminal success filter:
  - `status == COMPLETED`
  - `toChainId == 137`
  - `toTokenAddress == pUSD`
- Keeps CI network-free: tests monkeypatch adapter requests and use mocked docs-shaped payloads.

### Config

Added Bridge/pUSD constants:

- `POLYMARKET_BRIDGE_URL`
- `POLYMARKET_BRIDGE_TIMEOUT_SECONDS`
- `PUSD_POLYGON`
- `USDT_BRIDGE_POLYGON`

`.env.example` documents the non-secret Bridge URL and token constants.

### Schema substrate

Added migration `100_bridge_pusd_settlement.sql`:

- `bridge_deposit_addresses`
- `bridge_deposit_events`
- unique bridge address / tx-hash indexes
- event fields for original source token/chain/amount, target chain/token, normalized credited amount, raw JSON, status, and manual-review reason
- RLS enabled on both tables

This migration does not enable user-facing native USDC/USDT by itself.

### Deposit asset truth

Updated `wallet/deposit_assets.py` to replace the prior vague “conversion path missing” wording with Bridge/pUSD truth:

- native USDC is Bridge-supported, but raw native-USDC deposits stay detect-only until Bridge address/status settlement is active;
- USDT is Bridge-supported, but remains disabled until terminal Polygon pUSD settlement can be credited;
- USDC.e remains the only fully enabled option.

### Web notifications

Added `persist_user_alert_once()` in `webtrader/backend/notification_prefs.py`:

- writes WebTrader `system_alerts` once per user + alert kind + dedup key;
- stores `dedup_key` in metadata;
- fail-soft if alert persistence is unavailable.

Wired confirmed-money alerts:

- deposit confirmed/credited path writes `alert_kind='deposit_confirmed'` only after ledger credit;
- withdrawal completed path writes `alert_kind='withdrawal_confirmed'` only after status becomes completed and tx hash is recorded;
- Telegram notification behavior remains intact but is not the only user-visible receipt.

## Enabled / disabled matrix

| Token | Network | Bridge advertised | Raw watcher/custody | User-facing enabled | Reason |
|---|---:|---:|---:|---:|---|
| USDC.e | Polygon | Yes | Yes | Yes | Existing proven USDC.e deposit/watch/credit/sweep path |
| Native USDC | Polygon | Yes | Detect-only raw wrong-token lane | No | No active Bridge status poller currently credits terminal pUSD settlement |
| USDT | Polygon | Yes | No raw watcher/sweep | No | No active Bridge status poller currently credits terminal pUSD settlement |
| Base/Arbitrum USDC | non-Polygon | Out of scope | No | No | Lane is Polygon-only |

## Safety invariants preserved

- No real live orders.
- No real fund movement in tests.
- No CI calls to external Bridge endpoints.
- No custom DEX/swap route.
- No raw native USDC/USDT credit to available live balance.
- No live guard flips:
  - `USE_REAL_CLOB` unchanged.
  - `EXECUTION_PATH_VALIDATED` unchanged.
  - `ENABLE_LIVE_TRADING` unchanged.
  - `CAPITAL_MODE_CONFIRMED` unchanged.
- Pending/processing Bridge statuses are not creditable by the adapter.
- Only terminal `COMPLETED` records targeting Polygon pUSD are classified as pUSD settlement.
- Existing USDC.e behavior remains intact.
- $5 live Auto-Trade gate remains unchanged.

## Validation evidence

Commands run:

```text
python3 -m compileall projects/polymarket/crusaderbot/integrations/polymarket_bridge.py projects/polymarket/crusaderbot/config.py projects/polymarket/crusaderbot/wallet/deposit_assets.py projects/polymarket/crusaderbot/scheduler.py projects/polymarket/crusaderbot/wallet/withdrawals.py projects/polymarket/crusaderbot/webtrader/backend/notification_prefs.py projects/polymarket/crusaderbot/tests/test_polymarket_bridge.py projects/polymarket/crusaderbot/tests/test_money_lifecycle_web_notifications.py
```

Result: PASS.

```text
python3 -m ruff check projects/polymarket/crusaderbot/integrations/polymarket_bridge.py projects/polymarket/crusaderbot/config.py projects/polymarket/crusaderbot/wallet/deposit_assets.py projects/polymarket/crusaderbot/scheduler.py projects/polymarket/crusaderbot/wallet/withdrawals.py projects/polymarket/crusaderbot/webtrader/backend/notification_prefs.py projects/polymarket/crusaderbot/tests/test_polymarket_bridge.py projects/polymarket/crusaderbot/tests/test_money_lifecycle_web_notifications.py
```

Result: PASS.

```text
pytest -q projects/polymarket/crusaderbot/tests/test_polymarket_bridge.py projects/polymarket/crusaderbot/tests/test_money_lifecycle_web_notifications.py projects/polymarket/crusaderbot/tests/test_deposit_assets.py projects/polymarket/crusaderbot/tests/test_polygon_deposit_enablement.py
```

Result: PASS — 43 passed, 1 warning (websockets deprecation warning from installed dependency).

## Follow-up / next gate

- WARP🔹CMD first-pass PR review.
- WARP•R00T finishing pass or WARP•SENTINEL validation before merge because this lane touches custody/capital/deposit-accounting surfaces.
- A future lane may schedule the Bridge status poller and enable native USDC/USDT only after proving terminal pUSD settlement credit/reconciliation end-to-end.
