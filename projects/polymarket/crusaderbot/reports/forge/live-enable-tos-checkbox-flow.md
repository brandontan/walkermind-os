# WARP•FORGE Report — live-enable-tos-checkbox-flow

**Project:** CrusaderBot  
**Project Root:** projects/polymarket/crusaderbot  
**Branch:** WARP/live-enable-tos-checkbox-flow  
**Issue:** #1787  
**Validation Tier:** MAJOR  
**Claim Level:** NARROW INTEGRATION  
**Last Updated:** 2026-06-12 22:20 Asia/Jakarta

## Scope

Replace WebTrader LIVE enable typed-phrase consent with a Terms/risk checkbox flow, preserve self-serve PAPER -> LIVE semantics, and audit the accepted consent without changing live order placement, strategy logic, risk constants, or platform live guard flags.

## Implementation

- WebTrader LIVE modal now uses a checkbox acknowledgement tied to `LIVE_ENABLE_CONSENT_VERSION` instead of typed phrase input.
- WebTrader API client now submits `consent_accepted` and `consent_version` to `/live/enable`.
- Backend `LiveEnableRequest` accepts explicit checkbox consent and keeps `confirm_phrase` only as a stale-client compatibility field; typed phrase is no longer required.
- Backend `/live/enable` rejects missing consent with HTTP 400, validates the stable consent version, records accepted timestamp/version/user/surface/source in the audit payload, and still routes the actual mode switch through `live_mode.enable_live_self_serve`.
- 2FA remains present and optional/recommended for account and withdrawal protection; no 2FA setup/status/verify/disable surface was removed.
- Auto-Trade remains forced OFF by `enable_live_self_serve`; LIVE Auto-Trade arming remains gated by the shared >= $5 confirmed available live USDC.e guard.
- No `USE_REAL_CLOB`, `EXECUTION_PATH_VALIDATED`, `ENABLE_LIVE_TRADING`, or `CAPITAL_MODE_CONFIRMED` flag was changed.

## Files Changed

- `projects/polymarket/crusaderbot/domain/activation/live_opt_in_gate.py`
- `projects/polymarket/crusaderbot/webtrader/backend/schemas.py`
- `projects/polymarket/crusaderbot/webtrader/backend/router.py`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/LiveActivationModal.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/SettingsPage.tsx`
- `projects/polymarket/crusaderbot/tests/test_live_activation_flow.py`
- State files: `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `projects/polymarket/crusaderbot/state/WORKTODO.md`, `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## Validation

- PASS: `python3 -m py_compile projects/polymarket/crusaderbot/tests/test_live_activation_flow.py projects/polymarket/crusaderbot/webtrader/backend/router.py projects/polymarket/crusaderbot/webtrader/backend/schemas.py projects/polymarket/crusaderbot/domain/activation/live_opt_in_gate.py`
- PASS: `pytest -q projects/polymarket/crusaderbot/tests/test_live_activation_flow.py projects/polymarket/crusaderbot/tests/test_live_mode_truth.py projects/polymarket/crusaderbot/tests/test_self_serve_live_mode.py projects/polymarket/crusaderbot/tests/test_totp_2fa.py projects/polymarket/crusaderbot/tests/test_live_checklist.py` — 65 passed.
- PASS: `ruff check projects/polymarket/crusaderbot/webtrader/backend/router.py projects/polymarket/crusaderbot/webtrader/backend/schemas.py projects/polymarket/crusaderbot/domain/activation/live_opt_in_gate.py projects/polymarket/crusaderbot/tests/test_live_activation_flow.py`
- PASS: `npm run build` in `projects/polymarket/crusaderbot/webtrader/frontend`.
- PASS: visual smoke rendered locally; binary screenshot intentionally not committed because the PR system rejects binary files.

## Notes / Boundaries

- No real fund movement occurred.
- No network call requiring real secrets was used.
- No live order placement or live-fire validation was performed.
- The route remains self-serve: no admin approval, mandatory 2FA, deposit, or operator guard is required for the mode switch itself. Operator/global live unlock and the shared $5 live Auto-Trade guard still control real live arming/order placement.

## State

State: FORGE build complete on `WARP/live-enable-tos-checkbox-flow`; MAJOR lane requires WARP•SENTINEL or WARP•R00T final gate before merge.
