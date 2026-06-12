# FORGE Report — multi-asset-deposit-selector

Project: CrusaderBot
Branch: WARP/multi-asset-deposit-selector
Issue: #1793
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Status: FORGE build complete — pending WARP🔹CMD first-pass PR check and MAJOR final validation gate
Last Updated: 2026-06-12 23:49

## Summary

Implemented a conservative multi-asset WebTrader deposit selector that separates token and network truth while enabling only the asset path currently supported end-to-end by watcher, ledger, and custody sweep behavior: **USDC.e on Polygon**.

Disabled/unavailable options are visible as honest capability truth, but they do not receive a deposit address, QR code, or copyable deposit instruction.

## Scope Delivered

- Added `wallet/deposit_assets.py` as the explicit supported-deposit-asset model and allowlist.
- Added WebTrader API `DepositOption` contract and included `deposit_options` in `GET /wallet`.
- Replaced hardcoded DepositModal `Polygon / USDC only` copy with a token + network selector.
- Preserved current custody-aware deposit address behavior for the enabled Polygon USDC.e option.
- Kept native Polygon USDC, USDT, Base USDC, and Arbitrum USDC unavailable because the backend does not safely credit/sweep/reconcile those paths today.
- Added migration `098_deposit_asset_audit.sql` so deposit rows preserve original token/network/chain/contract/decimals and normalized USDC credit amount.
- Updated watcher record/confirm path to write and audit selected asset metadata and to credit from normalized USDC amount.
- Left wrong-token native-USDC detection credit-neutral.
- Preserved LIVE Auto-Trade start gate behavior; no live guard flags were flipped.

## Supported Asset Truth

| Asset ID | Token | Network | Selectable | Reason |
|---|---:|---:|---:|---|
| `polygon-usdc-e` | USDC.e | Polygon | YES | Current watcher scans configured `USDC_POLYGON`; ledger credits normalized USDC; custody sweep uses the same configured token. |
| `polygon-usdc-native` | USDC | Polygon | NO | Detection/alert only via wrong-token path; not credited or swept. |
| `polygon-usdt` | USDT | Polygon | NO | No watcher, ledger normalization, or custody sweep support. |
| `base-usdc` | USDC | Base | NO | No chain watcher or reconciliation support. |
| `arbitrum-usdc` | USDC | Arbitrum | NO | No chain watcher or reconciliation support. |

## Safety Notes

- Unsupported assets cannot produce deposit instructions in the UI.
- Disabled options deliberately return `deposit_address = null` in the API.
- The QR code and copy instruction are generated only for the selected enabled option.
- The watcher rejects transfer metadata whose scanned token address does not match the primary enabled deposit asset.
- Deposit ledger credits remain tied to `deposits.id`, preserving the existing live-bucket filter.
- `USE_REAL_CLOB`, `EXECUTION_PATH_VALIDATED`, `ENABLE_LIVE_TRADING`, and `CAPITAL_MODE_CONFIRMED` were not changed.

## Validation

Passed:
- `python3 -m py_compile projects/polymarket/crusaderbot/wallet/deposit_assets.py projects/polymarket/crusaderbot/scheduler.py projects/polymarket/crusaderbot/integrations/polygon.py projects/polymarket/crusaderbot/webtrader/backend/router.py projects/polymarket/crusaderbot/webtrader/backend/schemas.py projects/polymarket/crusaderbot/tests/test_deposit_assets.py projects/polymarket/crusaderbot/tests/test_deposit_reorg.py`
- `pytest -q projects/polymarket/crusaderbot/tests/test_deposit_assets.py projects/polymarket/crusaderbot/tests/test_deposit_reorg.py` — 12 passed, 1 third-party deprecation warning.
- `ruff check projects/polymarket/crusaderbot/wallet/deposit_assets.py projects/polymarket/crusaderbot/scheduler.py projects/polymarket/crusaderbot/integrations/polygon.py projects/polymarket/crusaderbot/webtrader/backend/router.py projects/polymarket/crusaderbot/webtrader/backend/schemas.py projects/polymarket/crusaderbot/tests/test_deposit_assets.py projects/polymarket/crusaderbot/tests/test_deposit_reorg.py`
- `npm --prefix projects/polymarket/crusaderbot/webtrader/frontend run build`

Warnings / environment limitations:
- Screenshot capture attempted after Vite startup and Playwright browser install, but Chromium could not launch in this container because `libatk-1.0.so.0` is missing. Build validation passed.

## Not in Scope / Deferred

- No USDT crediting path.
- No native USDC crediting path.
- No Base/Arbitrum/Ethereum watcher or bridge integration.
- No real fund movement or live-fire validation.
- No Auto-Trade behavior changes.
- No live guard flag changes.

## Next Gate

WARP🔹CMD first-pass PR check, then WARP•R00T finishing pass or WARP•SENTINEL approval/conditional approval because this is MAJOR custody/capital/deposit-accounting work.
