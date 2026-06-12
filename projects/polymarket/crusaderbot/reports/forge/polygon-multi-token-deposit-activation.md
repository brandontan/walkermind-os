# FORGE Report — polygon-multi-token-deposit-activation

Project: CrusaderBot
Branch: warp/activate-polygon-multi-token-deposit
Issue: #1796
PR: #1798
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Status: FORGE build + WARP•R00T finishing pass — R00T final gate (self-merge on CI green)
Last Updated: 2026-06-13 03:25

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

---

## WARP•R00T Finishing Pass (PR #1798)

Last Updated : 2026-06-13 03:25 Asia/Jakarta
Decision     : APPROVE — WARP•R00T takes final gate responsibility, self-merge on CI green. WARP•SENTINEL did NOT run and is not claimed.

### CMD first-pass blockers — disposition

- **BLOCKER 1 (MAJOR final gate missing)** — RESOLVED. WARP•R00T takes final gate responsibility (this report + PR body). Branch is a clean descendant of current main (which already has #1795's migration 099 — no collision; this lane does not re-add it).
- **BLOCKER 2 (branch traceability)** — FIXED. Exact head `warp/activate-polygon-multi-token-deposit` across this report, PROJECT_STATE, WORKTODO, CHANGELOG, and the PR body (was `WARP/polygon-multi-token-deposit-activation`).
- **BLOCKER 3 (PROJECT_STATE overclaim)** — FIXED. The pre-merge `BUILT #1796` entry no longer sits as completed truth; the Status line + entry read R00T-FINISHED MERGED #1798 (lands on main only on the actual merge).
- **BLOCKER 4 (PR title/body overclaim)** — FIXED. Title/body rewritten to code truth: a Polymarket-style Polygon selector with conservative asset gating — ONLY USDC.e enabled end-to-end; native USDC detect-only; USDT disabled. Required gate summary added.
- **BLOCKER 5 (sweep safety source-pinned, not behavior-pinned)** — FIXED. Added behaviour-level tests in `tests/test_sweep_deposits.py` with a mock that EMULATES the asset WHERE-clause against the bound params: `test_onchain_sweep_only_marks_primary_asset_rows_not_unsupported_tokens` (USDC.e + legacy-NULL swept; native USDC + USDT never selected/marked), `test_onchain_sweep_failure_only_manual_reviews_primary_asset_rows` (a co-located USDT row is not moved to manual_review by a USDC.e sweep failure), and `test_onchain_sweep_user_scoped_path_applies_same_asset_filter` (the realtime per-user path applies the identical filter — a native-only user is not selected, no UPDATE bound). The original source-pin is retained.

### CMD hardening items — disposition

1. **Frontend `chain_id === 137` hardcode** — kept, explicitly documented as #1796 Polygon-only scope (`selectableChains = ["Polygon"]` + the `chain_id === 137` token filter). Cross-chain derivation deferred until a second chain is actually enabled.
2. **`selected` cross-chain fallback** — FIXED. `selected` now falls back within the chosen chain's `tokenOptions` only (`tokenOptions.find(selectedId) ?? tokenOptions.find(enabled) ?? tokenOptions[0]`), never to an enabled option on another chain. Pinned by `test_deposit_modal_selection_invariant_local_to_selected_chain`.
3. **Disabled-asset selection** — VERIFIED. The token `<select>` marks unsupported options `disabled`, and the `onChange` handler commits only `if (next?.enabled)`, so a disabled token can never become `selected` → `selectedAddress=""` gates QR + address + copy off. Pinned by `test_deposit_modal_disabled_token_select_cannot_change_selection`.
4. **Native USDC / USDT activation** — NOT activated (no safe watcher/normalization/custody/reconcile/audit path); kept disabled with documented reasons.

### Validation (finishing pass)

- Targeted: `test_sweep_deposits.py` 13 passed (incl. 3 new behaviour tests), `test_deposit_assets.py` 19 passed.
- Full suite green; ruff + py_compile clean; frontend `npm run build` green.
- Secret-pattern + UTF-8/mojibake/BOM scans clean; branch verified from `git rev-parse`.

### Inviolable invariants — confirmed clean

No `USE_REAL_CLOB` / `EXECUTION_PATH_VALIDATED` / `ENABLE_LIVE_TRADING` / `CAPITAL_MODE_CONFIRMED` flip; on-chain sweep stays double-gated (`EXECUTION_PATH_VALIDATED` + `SWEEP_ONCHAIN_ENABLED`); wrong/unsupported token path credit-neutral; `$5` LIVE Auto-Trade gate unchanged; no risk-constant / Kelly change; no secrets; no real fund movement; asyncio only.
