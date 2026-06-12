# WARP•FORGE Report — polymarket-builder-relayer-cutover

**Project:** CrusaderBot (`projects/polymarket/crusaderbot`)  
**Branch:** `WARP/polymarket-builder-relayer-cutover`  
**Issue:** #1776  
**Validation Tier:** MAJOR  
**Claim Level:** NARROW INTEGRATION  
**Last Updated:** 2026-06-12 15:33 Asia/Jakarta

## Scope

Cut the readiness/configuration layer over to the current Polymarket Builder + dedicated Relayer key model without live-fire trading, without changing risk constants, and without auto-opening any live execution guard.

## Built

1. `RELAYER_API_KEY` + `RELAYER_API_KEY_ADDRESS` are now first-class readiness facts, reported separately from Builder client credentials.
2. Existing Builder relayer credential resolution remains backward compatible and now accepts `POLY_BUILDER_API_SECRET` as an alias for internal `POLY_BUILDER_SECRET`; canonical `POLY_BUILDER_SECRET` still wins.
3. Added a lightweight non-secret readiness truth helper for operator/admin surfaces. It reports:
   - real CLOB armed state
   - relayer configured state
   - relayer API key address configured state
   - Builder credentials configured state
   - Builder code/address configured state
   - custody mode (`eoa`, `safe`, `deposit_wallet`, `unknown`)
   - signature type
   - funder/deposit-wallet source
   - execution path validated state
4. `/admin/live-gate` now includes the readiness truth payload.
5. Telegram `/admin live` now displays the same readiness truth without logging or exposing secret values.
6. Startup custody posture logging now distinguishes Builder-client readiness from dedicated Relayer API-key readiness.

## Safety / Non-Scope Confirmation

- No live order was placed.
- No network call requiring real secrets was added or run.
- No live guard was auto-flipped (`USE_REAL_CLOB`, `EXECUTION_PATH_VALIDATED`, `ENABLE_LIVE_TRADING`, and related guards remain operator controlled).
- No risk constants were changed.
- Per-user max-concurrent and daily-loss precedence were preserved and covered by existing targeted tests.
- No secret values were written to repo, logs, report, or tests beyond synthetic fixture sentinels.

## Validation

- `python3 -m py_compile projects/polymarket/crusaderbot/config.py projects/polymarket/crusaderbot/integrations/builder_relayer.py projects/polymarket/crusaderbot/services/validation/live_readiness_truth.py projects/polymarket/crusaderbot/api/admin.py projects/polymarket/crusaderbot/bot/handlers/admin.py projects/polymarket/crusaderbot/main.py projects/polymarket/crusaderbot/tests/test_builder_relayer_cutover.py`
- `pytest -q projects/polymarket/crusaderbot/tests/test_builder_relayer_cutover.py projects/polymarket/crusaderbot/tests/test_gasless_custody.py projects/polymarket/crusaderbot/tests/test_startup_live_readiness.py projects/polymarket/crusaderbot/tests/test_sdk_rpc_pin.py projects/polymarket/crusaderbot/tests/test_concurrency_policy.py projects/polymarket/crusaderbot/tests/test_risk_limit_reconciliation.py` → 68 passed, 1 skipped, 1 warning.

## Next Gate

WARP•SENTINEL is required before merge because this is MAJOR live execution/capital-path readiness work.
