# FORGE Report — polygon-multi-token-deposit-activation

Project: CrusaderBot
Branch: WARP/polygon-multi-token-deposit-activation
Issue: #1796
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Status: FORGE build complete — pending WARP🔹CMD first-pass PR check and WARP•R00T/SENTINEL final gate
Last Updated: 2026-06-13 02:38

## Summary

Built the scoped #1796 activation pass without fake-enabling unsupported assets. The WebTrader deposit modal now presents a Polymarket-style token dropdown plus a Polygon-only chain dropdown, while backend custody/accounting truth remains conservative: **USDC.e on Polygon** is the only selectable end-to-end supported deposit asset. Native Polygon USDC and Polygon USDT remain disabled with explicit reasons because CrusaderBot still lacks safe conversion/custody/reconciliation for those assets.

## Scope Delivered

- Reworked `DepositModal.tsx` from the prior static card-list selector into dropdown selectors:
  - token selector/dropdown,
  - chain selector/dropdown,
  - Polygon as the only selectable chain in this lane,
  - support-status list showing unavailable Polygon tokens and reasons.
- Preserved QR/address/copy gating: only the selected enabled asset can render a QR code, raw address, or copy action.
- Preserved COPY contract: clipboard receives the raw selected deposit address only.
- Kept native Polygon USDC credit-neutral (wrong-token detect/alert lane) and kept Polygon USDT unavailable because no safe watcher/ledger/custody/reconciliation path exists.
- Hardened `_sweep_deposits_onchain()` so the USDC.e custody sweep path selects and updates only primary enabled asset deposit rows (`network`, `chain_id`, `token_address`), while allowing legacy rows whose `token_address` is NULL from before migration 099.
- Preserved LIVE Auto-Trade start guard and all global live guard flags.

## Supported Asset Truth

| Asset ID | Token | Network | Selectable | Reason |
|---|---:|---:|---:|---|
| `polygon-usdc-e` | USDC.e | Polygon | YES | Watcher scans configured `USDC_POLYGON`; ledger credits normalized USDC; custody sweep uses the same enabled token path. |
| `polygon-usdc-native` | USDC | Polygon | NO | Detect/alert only through wrong-token lane; not credited, not swept, not tradeable as Polymarket collateral without conversion. |
| `polygon-usdt` | USDT | Polygon | NO | No configured safe watcher, normalization, custody sweep, reconciliation, or conversion path in this lane. |
| non-Polygon options | USDC | Base/Arbitrum | NO | Outside #1796 requested active network scope. |

## Safety Notes

- UI enabled still equals backend safe end-to-end. No disabled asset gets an address, QR code, or copyable deposit instruction.
- Unsupported-token transfers remain credit-neutral and operator-visible via the wrong-token table/path where applicable.
- The on-chain sweep path no longer treats all confirmed deposit rows for a user as sweepable USDC.e rows; it scopes reads and updates to the primary enabled asset.
- `USE_REAL_CLOB`, `EXECUTION_PATH_VALIDATED`, `ENABLE_LIVE_TRADING`, and `CAPITAL_MODE_CONFIRMED` were not changed.
- No real fund movement occurred during validation.

## Validation

Passed:
- `python3 -m py_compile projects/polymarket/crusaderbot/wallet/deposit_assets.py projects/polymarket/crusaderbot/scheduler.py projects/polymarket/crusaderbot/tests/test_deposit_assets.py projects/polymarket/crusaderbot/tests/test_sweep_deposits.py`
- `pytest -q projects/polymarket/crusaderbot/tests/test_deposit_assets.py projects/polymarket/crusaderbot/tests/test_sweep_deposits.py` — 27 passed.
- `ruff check projects/polymarket/crusaderbot/wallet/deposit_assets.py projects/polymarket/crusaderbot/scheduler.py projects/polymarket/crusaderbot/tests/test_deposit_assets.py projects/polymarket/crusaderbot/tests/test_sweep_deposits.py`
- `npm --prefix projects/polymarket/crusaderbot/webtrader/frontend run build`

Warnings / environment limitations:
- Screenshot capture attempted after `npm install` and Playwright Chromium install, but Chromium could not launch in this container because `libatk-1.0.so.0` is missing. Build validation passed.

## Not in Scope / Deferred

- No native Polygon USDC crediting/conversion/sweep activation.
- No Polygon USDT crediting/conversion/sweep activation.
- No Base/Arbitrum/Ethereum/Solana deposit activation.
- No live-fire validation or real fund movement.
- No Auto-Trade behavior change and no live guard flag flip.

## Next Gate

WARP🔹CMD first-pass PR check, then WARP•R00T finishing pass or WARP•SENTINEL approval/conditional approval because this is MAJOR custody/capital/deposit-accounting work.
