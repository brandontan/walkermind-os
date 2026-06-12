# FORGE Report — multi-asset-deposit-selector

Project: CrusaderBot
Branch: warp/add-multi-asset-deposit-selector
Issue: #1793
PR: #1795
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Status: FORGE build + WARP•R00T finishing pass — R00T final gate (self-merge on CI green)
Last Updated: 2026-06-13 00:25

## Summary

Implemented a conservative multi-asset WebTrader deposit selector that separates token and network truth while enabling only the asset path currently supported end-to-end by watcher, ledger, and custody sweep behavior: **USDC.e on Polygon**.

Disabled/unavailable options are visible as honest capability truth, but they do not receive a deposit address, QR code, or copyable deposit instruction.

## Scope Delivered

- Added `wallet/deposit_assets.py` as the explicit supported-deposit-asset model and allowlist.
- Added WebTrader API `DepositOption` contract and included `deposit_options` in `GET /wallet`.
- Replaced hardcoded DepositModal `Polygon / USDC only` copy with a token + network selector.
- Preserved current custody-aware deposit address behavior for the enabled Polygon USDC.e option.
- Kept native Polygon USDC, USDT, Base USDC, and Arbitrum USDC unavailable because the backend does not safely credit/sweep/reconcile those paths today.
- Added migration `099_deposit_asset_audit.sql` (renumbered from 098 by R00T — 098 is taken by `ledger.archived` on main) so deposit rows preserve original token/network/chain/contract/decimals and normalized USDC credit amount.
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

---

## WARP•R00T Finishing Pass (PR #1795)

Last Updated : 2026-06-13 00:25 Asia/Jakarta
Decision     : APPROVE — WARP•R00T takes final gate responsibility, self-merge on CI green. WARP•SENTINEL did NOT run and is not claimed.

### CMD first-pass blockers — disposition

- **BLOCKER 1 (dirty / behind main)** — RESOLVED. Merged latest `origin/main` (includes #1794 paper-session reset); PROJECT_STATE/WORKTODO/CHANGELOG conflicts resolved onto the mainline shape, this lane re-applied truthfully.
- **BLOCKER 2 (migration numbering collision)** — CONFIRMED + FIXED. Main landed `098_ledger_archived.sql` (#1794) after this branch was cut; the deposit-asset migration is renumbered `098 → 099_deposit_asset_audit.sql` (header comment + report references updated). Pinned by `test_migration_099_adds_asset_audit_columns`, which also asserts 098 stays `ledger.archived`.
- **BLOCKER 3 (branch traceability)** — FIXED. Exact head `warp/add-multi-asset-deposit-selector` across this report, PROJECT_STATE, WORKTODO, CHANGELOG, and the PR body.
- **BLOCKER 4 (COPY broke the address contract)** — FIXED. `DepositModal.copyAddress()` copied an instruction sentence (`Deposit {token} on {network} to {address}`); wallets/exchanges paste copy output straight into a send form. COPY now writes the RAW selected address only (both the `navigator.clipboard` and `execCommand` fallback paths). Pinned by `test_deposit_modal_copy_writes_raw_address_only`.
- **BLOCKER 5 (PR body gate summary)** — FIXED. Body rewritten to code truth (conservative selector, only Polygon USDC.e enabled) with the required gate block.
- **BLOCKER 6 (no CI on head)** — RESOLVED on the finished head: full local suite + GitHub `Lint + Test` green before merge.

### CMD hardening items — disposition

1. **Token decimals propagation** — FIXED. `watch_deposits()` now passes `token_decimals=deposit_asset.decimals` into `polygon.scan_from_cursor` → `scan_usdc_transfers`, so amount decoding follows the enabled asset, never a hardcoded default.
2. **Falsy fallback correctness** — FIXED on both capital paths. `polygon.scan_usdc_transfers`: `token_decimals or settings.USDC_DECIMALS` → explicit `is None` (decimals=0 is a valid ERC-20 value). `scheduler._confirm_ready_deposits`: `normalized_amount_usdc or amount_usdc` → explicit `is None`; a legitimate zero normalized amount now credits 0, proven by the behaviour test `test_confirm_credits_zero_normalized_amount_not_raw`.
3. **Unsupported assets non-selectable end-to-end** — VERIFIED. Native `disabled` attribute (not keyboard-focusable per HTML semantics), `selectedAddress=""` for a disabled selection gates QR + copy off, API `deposit_address=null` for disabled options. Pinned by `test_deposit_modal_disabled_assets_not_selectable_no_qr` + FORGE's `test_api_options_do_not_attach_address_to_unavailable_assets`.
4. **Custody address truth** — VERIFIED post-merge. `/wallet` resolves the displayed address via `wallet.custody.effective_deposit_address(w_row)` (safe_address under `CUSTODY_MODE='safe'`), and `asset_api_options()` attaches that same custody-aware address only to the enabled asset.

### Codex review (P2) — reorg revert amount truth — FIXED

Codex flagged that `_confirm_ready_deposits` now credits `normalized_amount_usdc` while `_revert_deposit` (reorg `removed=true` rollback) still debited the raw `amount_usdc` — a non-1:1 (or zero) normalized deposit would over/under-debit the wallet on a reorg. `_revert_deposit` now `SELECT`s `normalized_amount_usdc` and applies the same explicit `is None` fallback before `ledger.debit_in_conn`, so the credit and the rollback always move the same value. Pinned by `test_confirmed_reorg_reverts_normalized_amount_not_raw` (normalized=42.5 vs raw=100.0 → debits 42.5).

### R00T also fixed (found during the pass)

- `tests/test_deposit_e2e.py` was broken by the FORGE change at the seams: (a) the `fake_scan` mocks branched on `token_address is None` for the primary scan, but the primary scan now passes the explicit USDC.e contract — the mocks now branch on the actual token contract, which upgrades the e2e into a behavioural proof that the primary scan is token-scoped and the wrong-token pass scans native USDC; (b) the deposits INSERT mock unpacked 5 args (now 11); (c) `primary_deposit_asset()` reads the real Settings — hermetic tests now patch the `scheduler.primary_deposit_asset` seam (same as the reorg harness).
- New `test_record_pending_rejects_mismatched_token_transfer` pins the no-unsupported-asset-crediting guard.

### Validation (finishing pass)

- Targeted deposit suite (e2e / reorg / assets / sweep): 23 passed + 15 asset tests.
- Full suite green; ruff + py_compile clean; frontend `npm run build` green.
- Secret-pattern + UTF-8/mojibake/BOM scans clean; branch verified from `git rev-parse`.

### Inviolable invariants — confirmed clean

No `USE_REAL_CLOB` / `EXECUTION_PATH_VALIDATED` / `ENABLE_LIVE_TRADING` / `CAPITAL_MODE_CONFIRMED` flip; wrong-token path stays credit-neutral; `$5` LIVE Auto-Trade start gate unchanged; no risk-constant / Kelly change; no secrets; no real fund movement; asyncio only.
