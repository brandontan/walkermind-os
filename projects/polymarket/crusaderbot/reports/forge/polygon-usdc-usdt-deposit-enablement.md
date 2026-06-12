# WARP•FORGE Report — polygon-usdc-usdt-deposit-enablement

Project: CrusaderBot
Project Root: projects/polymarket/crusaderbot
Branch: warp/polygon-usdc-usdt-deposit-enablement
Issue: #1800
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Status: FORGE build complete — pending WARP🔹CMD first-pass + WARP•R00T finishing pass
Last Updated: 2026-06-13 05:25 Asia/Jakarta

## Headline verdict (honest, per the issue's "keep disabled with reason" guardrail)

**Native Polygon USDC and Polygon USDT CANNOT be safely enabled end-to-end in this lane, so both remain DISABLED with explicit documented blockers. No token was fake-enabled.** This is the correct outcome under the issue's own product truth ("UI enabled means backend support is safe end-to-end. Do not fake-enable any token"; "If conversion is not implemented in this lane, keep USDT disabled and document blocker").

### Why — code-truth blocker

- **Custody sweep is USDC.e-contract-bound.** `integrations/polygon_usdc.sweep_usdc_to_master` (and `transfer_usdc`) hard-code `settings.USDC_POLYGON` (USDC.e) — there is no per-token-address parameter. A confirmed native-USDC or USDT row could never be swept to master by this path.
- **No conversion / bridge path exists.** Nothing in the repo converts native USDC → USDC.e or USDT → USDC.e. Polymarket's CTF/CLOB collateral in this system is USDC.e (`USDC_POLYGON`); native USDC and USDT are NOT collateral.
- **Therefore crediting them as confirmed available LIVE balance would be unsafe**: the user could not trade with the balance (not collateral) and it could not be swept/reconciled. That violates the issue's product truth #3 and the `$5` live-gate semantics.

Enabling either token requires a **new conversion-custody lane** (DEX swap or bridge → USDC.e, with slippage/settlement/reconcile), which is well beyond this NARROW INTEGRATION and explicitly out of scope.

## Token capability matrix (honest)

| Token / Network | detectable | creditable | sweepable | reconcilable | convertible | enabled | reason |
|---|:--:|:--:|:--:|:--:|:--:|:--:|---|
| USDC.e / Polygon | ✓ | ✓ | ✓ | ✓ | n/a | **ENABLED** | the configured collateral token — watched, credited, swept |
| USDC (native) / Polygon | ✓ | ✗ | ✗ | ✗ | ✗ | disabled | detect-only (wrong-token alert); not collateral; sweep is USDC.e-bound; no USDC→USDC.e conversion |
| USDT / Polygon | ✗ | ✗ | ✗ | ✗ | ✗ | disabled | not watched; requires a USDT→USDC.e conversion that does not exist |
| USDC / Base, Arbitrum | ✗ | ✗ | ✗ | ✗ | ✗ | disabled | non-Polygon — out of scope |

## What was built (real, in-scope)

1. **Explicit capability model** on `wallet/deposit_assets.DepositAsset` — the issue's vocabulary `detectable` / `creditable` / `sweepable` / `reconcilable` / `convertible` / `disabled_reason`, with honest per-token values (above). `enabled_deposit_assets()` now requires the FULL matrix (detectable+creditable+sweepable+reconcilable), so a future stray `enabled=True` without the backing capabilities can never fake-enable a token for real deposits. The matrix flows through `to_api` for admin/audit surfaces; both reason fields kept in sync.
2. **Precise disabled reasons** for native USDC + USDT documenting the conversion/sweep blocker (no longer the vague "not credited or swept").
3. **CMD UI scope update — capability cards removed.** `DepositModal.tsx` no longer renders the stacked per-token capability-card list. The user sees: token dropdown + Polygon chain dropdown + a **compact selected-token status** (Supported / Unavailable + concise reason) + QR + raw deposit address + copy + the existing concise warnings (send-only-selected-token, wrong-token-loss risk, live-mode-real-funds). Disabled token → `selectedAddress=""` gates off QR/address/copy. COPY still writes the raw address only.
4. Native USDC stays detect-only / credit-neutral via the existing `_alert_wrong_token_deposits` wrong-token lane (#1793/#1795) — unchanged; operator-visible, never credited.

## Preserved invariants (verified by test)

- USDC.e behavior + #1795/#1798 sweep asset-scoping tests intact (32 deposit/sweep tests green).
- Reorg revert debits the NORMALIZED credited amount (explicit is-None fallback), not the raw token amount — done-criterion 10 (already landed #1795; pinned here).
- Original token/network/tx/raw amount/decimals/normalized amount preserved on every deposit row (migration 099 columns; pinned).
- Wrong/unsupported token path remains credit-neutral; the USDC.e sweep cannot select/mark a non-USDC.e row (#1798 behaviour tests).
- `$5` LIVE Auto-Trade gate + live guard flags unchanged; no `USE_REAL_CLOB`/`EXECUTION_PATH_VALIDATED`/`ENABLE_LIVE_TRADING`/`CAPITAL_MODE_CONFIRMED` flip.

## Files Changed

- projects/polymarket/crusaderbot/wallet/deposit_assets.py (capability matrix + honest reasons + full-matrix gate)
- projects/polymarket/crusaderbot/webtrader/frontend/src/components/DepositModal.tsx (remove capability cards → compact status)
- projects/polymarket/crusaderbot/tests/test_polygon_deposit_enablement.py (new, 16 tests)
- state/PROJECT_STATE.md, state/WORKTODO.md, state/CHANGELOG.md

## Validation

- New `test_polygon_deposit_enablement.py`: 16 passed. Adjacent deposit/wallet/sweep regression: 281 passed.
- Full suite: **3583 passed, 11 skipped**. ruff + py_compile clean on touched Python; frontend `npm run build` green.
- Secret-pattern + UTF-8/mojibake/BOM scans clean. Branch verified from `git rev-parse`. No real fund movement, no network call requiring secrets.

## Enabled / disabled token matrix (deliverable summary)

- ENABLED end-to-end: **USDC.e on Polygon** only.
- DISABLED with documented blocker: native USDC on Polygon, USDT on Polygon, USDC on Base/Arbitrum.

## What is next

- To enable native USDC or USDT: a future conversion-custody lane (swap/bridge → USDC.e + settlement + reconcile + reorg/audit), then flip `creditable/sweepable/reconcilable/convertible` + `enabled` once proven. Until then they stay disabled by capability-gate truth.

## Next Gate

WARP🔹CMD first-pass PR check → WARP•R00T finishing pass. MAJOR custody/capital/deposit-accounting — final merge requires WARP•R00T final gate or WARP•SENTINEL.
