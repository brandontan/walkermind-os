# WARP•SENTINEL — Admin Live Truth Fresh Validation Rerun

Last Updated: 2026-06-12 14:27
Role: WARP•SENTINEL
Project: CrusaderBot
Project Root: `projects/polymarket/crusaderbot`
PR: #1771
Branch Validated: `WARP/root-admin-live-truth`
Current Local Branch Label: `work` (Codex worktree label only; artifact branch traceability uses PR head branch above)
Head SHA Validated: `ea07bf8de8b7adf0b6511d0cc7c68483a43a0c9f`
Tier: MAJOR
Claim Level: NARROW INTEGRATION
Verdict: APPROVED

## Scope Validated

Validated current head only (`ea07bf8de8b7adf0b6511d0cc7c68483a43a0c9f`). Stale Sentinel artifact #1774 was not reused as evidence.

Covered:
- Mandatory WARP🔹CMD blocker pre-checks after cleanup merge.
- Admin Users roster live/paper balance and open-position mode scoping.
- Admin Backfill UI deposit-wallet + safes summary rendering, including failure-message preservation of safes summary.
- SDK gasless `api_key` wiring for Polymarket `AsyncSecureClient.create(...)` call sites under `projects/polymarket/crusaderbot/integrations/clob`.
- Live execution safety boundaries: order path enablement, risk constants, bankroll/Kelly/sizing, and `ENABLE_LIVE_TRADING` guard behavior.

## Mandatory Pre-Check Result

Status: PASS — both old WARP🔹CMD blockers are resolved on current head.

1. `projects/polymarket/crusaderbot/webtrader/backend/router.py`
   - `/admin/users` now assigns `live_ledger_filter = live_ledger_filter_sql("l")` and uses that value for `live_balance_usdc`.
   - Static slice check over the `/admin/users` endpoint confirmed no duplicated manual deposits-table/live-ledger predicate remains in that bucket.
   - Open-position count is scoped by `p.mode = COALESCE(st.trading_mode, 'paper')`.

2. `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
   - Current state uses the full repo-root report path exactly: `projects/polymarket/crusaderbot/reports/forge/admin-live-truth.md`.

## Evidence

### Admin Users roster

- `/admin/users` computes `live_balance_usdc` from the centralized wallet-ledger predicate via `live_ledger_filter_sql("l")` and returns mode-scoped displayed balances: LIVE rows get `live_balance_usdc`; PAPER rows get `wallets.balance_usdc - live_balance_usdc` clamped at zero.
- `/admin/users` open-position count is filtered by the row's current trading mode (`p.mode = COALESCE(st.trading_mode, 'paper')`).
- `wallet/ledger.py` remains the canonical live-money truth source: real deposits are `type='deposit'` with a deposits-table-backed `ref_id`; withdrawals, withdrawal refunds, and live-position ledger rows are included; paper resets/manual paper flow stay outside the live bucket.
- Semantics align with wallet live ledger truth: the admin roster reuses the exact live ledger predicate and derives paper by subtracting the same live bucket from the mixed wallet balance.

### Admin Backfill UI

- Backend `/admin/backfill-deposit-wallets` returns the deposit-wallet summary plus optional `safes` summary and preserves `safes` in the response even when `ok` is false.
- Frontend `api.backfillDepositWallets()` type now includes optional `safes?: { scanned; filled; skipped }`.
- `AdminPage.handleBackfill()` renders the deposit-wallet summary and appends the safes summary when present for both success and aborted/failure status messages returned by the backend.
- Network/exception catch still reports the thrown error message only; no backend summary exists in that thrown path, so there is no safes summary to preserve there.

### SDK gasless api_key wiring

`RELAYER_API_KEY` and `RELAYER_API_KEY_ADDRESS` are present in `Settings` and `sdk_env.sdk_api_key()` maps them to `polymarket.auth.RelayerApiKey(key=..., address=...)`.

Preference validated:
- Relayer key wins over settings-level builder key inside `sdk_env.sdk_api_key()`.
- Builder key remains fallback when relayer fields are absent.
- `None` remains allowed when neither relayer nor builder credentials are configured, preserving already-deployed-wallet resolve behavior.

Inspected `AsyncSecureClient.create(...)` call sites:

| File | Line | Call Site | `environment=production_environment()` | `api_key=...` |
|---|---:|---|---|---|
| `projects/polymarket/crusaderbot/integrations/clob/__init__.py` | 226 | `ensure_clob_credentials()` POLY_1271 derive path | yes | yes, `sdk_api_key()` |
| `projects/polymarket/crusaderbot/integrations/clob/sdk_client.py` | 180 | `PolymarketSdkClient._ensure()` | yes | yes, client-local builder key when explicitly supplied, otherwise `sdk_api_key()` |
| `projects/polymarket/crusaderbot/integrations/clob/user_client.py` | 138 | `resolve_deposit_wallet()` | yes | yes, `sdk_api_key()` |
| `projects/polymarket/crusaderbot/integrations/clob/user_client.py` | 180 | `resolve_deposit_wallet_creds()` | yes | yes, `sdk_api_key()` |

AST validation over `projects/polymarket/crusaderbot/integrations/clob/**/*.py` found no `AsyncSecureClient.create(...)` call missing either `environment` or `api_key`.

### Live execution safety

- No order-execution path is newly enabled by this PR. Defaults remain `USE_REAL_CLOB=False`, `USE_PYSDK_CLOB=False`, `USE_CLOB_V2=False`, `USE_RUST_SIDECAR=False`, and `USE_PER_USER_EXECUTION=False`.
- `ENABLE_LIVE_TRADING` remains default `False` and was not weakened.
- Risk/capital constants in `config.py` remain unchanged in the PR diff: `MAX_SINGLE_POSITION_PCT=0.05`, `MAX_TOTAL_EXPOSURE_PCT=0.60`, `MAX_DAILY_LOSS_USD=-50.00`, `MAX_OPEN_POSITIONS=20`.
- The PR changed CLOB SDK environment/api-key construction, admin read-model behavior, frontend display typing/rendering, tests, and state/report artifacts; it did not modify live execution routing, gate evaluation, bankroll/Kelly/sizing logic, or order-placement guards.

## Commands Run

- PASS: `git rev-parse HEAD`
  - Output: `ea07bf8de8b7adf0b6511d0cc7c68483a43a0c9f`
- PASS: `git branch --show-current`
  - Output: `work` (Codex worktree label; PR branch traceability recorded as `WARP/root-admin-live-truth`)
- PASS: `python - <<'PY' ... /admin/users static pre-check ... PY`
  - Confirmed `uses_live_ledger_filter_sql_l=True`, `no_deposits_manual_predicate=True`, `open_positions_mode_scoped=True`.
- PASS: `python -m pytest projects/polymarket/crusaderbot/tests/test_gasless_custody.py projects/polymarket/crusaderbot/tests/test_sdk_rpc_pin.py`
  - Result: 18 passed, 35 warnings (pre-existing Python 3.14 invalid-escape SyntaxWarnings in bot message strings).
- PASS: `python -m pytest projects/polymarket/crusaderbot/tests/test_admin_backfill_trigger.py projects/polymarket/crusaderbot/tests/test_live_mode_truth.py`
  - Result: 18 passed.
- PASS: `python - <<'PY' ... AsyncSecureClient.create AST check ... PY`
  - Result: 4 call sites inspected; all include `environment` and `api_key`.
- WARNING: Initial `npm run build` in `projects/polymarket/crusaderbot/webtrader/frontend` failed before dependency installation because `node_modules` was absent in the fresh runner.
- PASS: `npm ci`
  - Result: 226 packages installed.
- PASS: `npm run build`
  - Result: `tsc && vite build` passed; Vite emitted one non-blocking dynamic/static import chunking warning for `PortfolioPage.tsx`.

## Files Inspected

- `projects/polymarket/crusaderbot/config.py`
- `projects/polymarket/crusaderbot/integrations/clob/sdk_env.py`
- `projects/polymarket/crusaderbot/integrations/clob/__init__.py`
- `projects/polymarket/crusaderbot/integrations/clob/sdk_client.py`
- `projects/polymarket/crusaderbot/integrations/clob/user_client.py`
- `projects/polymarket/crusaderbot/wallet/ledger.py`
- `projects/polymarket/crusaderbot/webtrader/backend/router.py`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AdminPage.tsx`
- `projects/polymarket/crusaderbot/tests/test_gasless_custody.py`
- `projects/polymarket/crusaderbot/tests/test_sdk_rpc_pin.py`
- `projects/polymarket/crusaderbot/tests/test_admin_backfill_trigger.py`
- `projects/polymarket/crusaderbot/tests/test_live_mode_truth.py`
- `projects/polymarket/crusaderbot/reports/forge/admin-live-truth.md`
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## Critical Issues

None.

## Non-Blocking Issues

- Fresh runner did not have frontend `node_modules`; `npm run build` failed until `npm ci` installed dependencies. After `npm ci`, the frontend build passed.
- Python 3.14 emitted pre-existing invalid-escape SyntaxWarnings in bot message strings during targeted pytest. These are unrelated to this PR's modified surfaces.
- Vite emitted a non-blocking chunking warning because `PortfolioPage.tsx` is both dynamically and statically imported. This is unrelated to this PR's modified Admin Backfill UI surface and did not fail the build.
- Observation for WARP🔹CMD awareness: `PolymarketSdkClient._ensure()` preserves existing client-local builder-credential precedence when that constructor is explicitly passed builder credentials; otherwise it falls back to `sdk_api_key()` where relayer wins over settings-level builder. This is not a blocker for the stated NARROW INTEGRATION claim because the deposit-wallet resolve/backfill paths use `sdk_api_key()` directly and the existing single-wallet pysdk order-client constructor behavior was not widened into a live-order enablement path.

## Merge Recommendation for WARP🔹CMD

APPROVE / READY FOR WARP🔹CMD MERGE DECISION.

The old WARP🔹CMD blockers are resolved on current head `ea07bf8de8b7adf0b6511d0cc7c68483a43a0c9f`, targeted backend and frontend validation passed after dependency installation, all CLOB SDK `AsyncSecureClient.create(...)` call sites carry both the production RPC environment and an `api_key` argument, `/admin/users` mode scoping now uses centralized wallet ledger truth, and no execution/risk/live-trading guard was weakened.
