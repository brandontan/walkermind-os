# WARP•FORGE Report — live-enable-tos-checkbox-flow

**Project:** CrusaderBot  
**Project Root:** projects/polymarket/crusaderbot  
**Branch:** warp/implement-live-enable-tos-checkbox-flow  
**Issue:** #1787  
**PR:** #1791  
**Validation Tier:** MAJOR  
**Claim Level:** NARROW INTEGRATION  
**Last Updated:** 2026-06-12 23:05 Asia/Jakarta

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

State: FORGE build complete on `warp/implement-live-enable-tos-checkbox-flow`; MAJOR lane requires WARP•SENTINEL or WARP•R00T final gate before merge.

---

## WARP•R00T Finishing Pass (PR #1791)

**Last Updated:** 2026-06-12 23:05 Asia/Jakarta
**Decision:** APPROVE — WARP•R00T takes final gate responsibility, self-merge on CI green. WARP•SENTINEL did NOT run and is not claimed.

### CMD first-pass blockers — disposition

- **BLOCKER 1 (dirty / behind main)** — RESOLVED. Merged latest `origin/main` (`#1789` mode-width migration + `#1790` health-probe severity); only conflict was `state/PROJECT_STATE.md`, resolved onto the mainline AGENTS.md-compliant shape, lane re-applied truthfully.
- **BLOCKER 2 (frontend blocked LIVE switch on operator/checklist readiness)** — FIXED. `LiveActivationModal` no longer computes a blocking `ready` gate: the preview→consent button is always enabled; operator/checklist readiness is rendered as status rows + a "Heads up — live Auto-Trade not ready yet" warning that explicitly says the user can still switch and lands as `LIVE ENABLED / WAITING FOR DEPOSIT`. The backend was already correct (`enable_live` never consulted `_operator_guards_open` / `live_checklist`) — pinned by `test_enable_live_is_self_serve_not_operator_or_admin_gated` and `test_enable_live_with_zero_balance_and_consent_succeeds_waiting_for_deposit`. New frontend source pin `test_live_modal_does_not_block_switch_on_operator_or_checklist_readiness` makes the regression fail CI.
- **BLOCKER 3 (stale 2FA copy)** — FIXED. `TwoFactorSetupCard`: "Required for live trading. Off — turn on before going live." → "Optional — recommended for account and withdrawal protection."; disable-flow copy "will block live trading" → optional-protection wording. All 2FA surfaces (setup/status/verify/disable) preserved — pinned by `test_two_factor_card_copy_is_optional_not_required`.
- **BLOCKER 4 (branch traceability)** — FIXED. Exact PR head branch `warp/implement-live-enable-tos-checkbox-flow` now used in this report, PROJECT_STATE, WORKTODO, CHANGELOG (the FORGE CHANGELOG entry, which the auto-merge had also mis-placed mid-file, was relocated to the top and corrected), and the PR body.
- **BLOCKER 5 (PR body gate summary)** — FIXED. Report / State / Validation Tier / Claim Level / Next Gate block added to the PR body.
- **BLOCKER 6 (no CI on head)** — RESOLVED on the finished head: targeted + full validation locally, GitHub `Lint + Test` confirmed green before merge.

### CMD hardening item — STRICT consent_version (decision: STRICT)

The FORGE build defaulted a missing `consent_version` to the server constant — a stale client could record consent against copy the user never rendered. R00T removed the default: `body.consent_version` must equal `LIVE_ENABLE_CONSENT_VERSION` exactly; missing OR stale → HTTP 400 with a refresh hint, before any state change. WebTrader always sends the version (`lib/api.ts` default parameter). Truly stale clients (typed-phrase era) fail earlier on `consent_accepted`. New pins: `test_enable_live_missing_consent_version_blocks_with_400`, `test_enable_live_stale_consent_version_blocks_with_400`.

### Files modified by the finishing pass (on top of FORGE)

- `projects/polymarket/crusaderbot/webtrader/backend/router.py` (strict consent_version)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/LiveActivationModal.tsx` (readiness no longer blocks switch)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/TwoFactorSetupCard.tsx` (optional/recommended copy)
- `projects/polymarket/crusaderbot/tests/test_live_activation_flow.py` (+4 tests: strict-version ×2, frontend source pins ×2; legacy-phrase test updated to carry the version)
- `state/PROJECT_STATE.md`, `state/WORKTODO.md`, `state/CHANGELOG.md` (repo-truth sync, exact branch)

### Validation (finishing pass)

- Targeted pytest (live activation / live mode / self-serve / 2FA / checklist + autotrade-guard pins): green — see PR body for counts.
- Full suite green; ruff + py_compile clean on touched Python; `npm run build` green on the touched frontend.
- Secret-pattern + UTF-8/mojibake/BOM scans clean. Branch traceability verified from `git rev-parse`.

### Inviolable invariants — confirmed clean

No `USE_REAL_CLOB` / `EXECUTION_PATH_VALIDATED` / `ENABLE_LIVE_TRADING` / `CAPITAL_MODE_CONFIRMED` flip; shared `$5` live Auto-Trade start guard and Auto-Trade-OFF-on-switch untouched (pinned by the #1784 toggle tests, all green); no risk-constant / Kelly change; no secrets; no real fund movement; asyncio only.
