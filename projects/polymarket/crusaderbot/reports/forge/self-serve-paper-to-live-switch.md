# WARP•FORGE Report — self-serve-paper-to-live-switch

Last Updated : 2026-06-12 21:30
Project      : CrusaderBot
Project Root : projects/polymarket/crusaderbot
Branch       : warp/implement-self-serve-paper-to-live-switch
Issue        : #1782
PR           : #1784
Tier         : MAJOR
Claim Level  : NARROW INTEGRATION

## Summary
Implemented self-serve PAPER -> LIVE mode activation semantics without bypassing real-money execution gates.

Users can now explicitly confirm a switch to LIVE mode without mandatory 2FA or per-user admin approval. The switch itself only records user consent and mode truth. It forces Auto-Trade OFF, archives paper simulation positions/orders out of live-facing surfaces, acknowledges existing user alerts so LIVE notifications start clean, and returns truthful `LIVE ENABLED / WAITING FOR DEPOSIT` status when confirmed available live USDC.e is below $5.

## Scope Implemented
- New `domain.activation.live_mode` helper for the PAPER -> LIVE transition.
- LIVE mode switch writes `trading_mode='live'` and `paper_mode_override=FALSE` together.
- LIVE mode switch forces `users.auto_trade_on=FALSE`.
- Paper simulation positions/orders are marked `paper_archived`; open/pending paper positions are closed with `exit_reason='paper_to_live_switch'` so they no longer appear in paper/live mode-scoped user surfaces.
- User alert watermark is advanced on switch (`alerts_ack_at=NOW()`) so pre-switch paper alerts do not appear as unread LIVE context.
- New hard minimum constant: `MIN_LIVE_AUTOTRADE_BALANCE_USDC = 5`.
- Telegram Auto-Trade LIVE start checks both live checklist readiness and confirmed available live USDC.e >= $5.
- MVP Auto-Trade start path checks the same LIVE readiness + $5 balance gate before setting `auto_trade_on=TRUE`.
- WebTrader `/live/enable` is self-serve typed-confirm mode activation and delegates state mutation to the shared helper.
- Live checklist no longer treats 2FA or admin role as hard gates; 2FA remains optional/recommended status.
- MVP mode-scoped balance/PnL/trade counts now use live balance in LIVE mode and paper balance/history in PAPER mode.

## Safety Boundaries Preserved
- No code flips `USE_REAL_CLOB`.
- No code flips `EXECUTION_PATH_VALIDATED`.
- No code bypasses `ENABLE_LIVE_TRADING` or operator/platform live guards.
- LIVE mode switch alone never starts Auto-Trade and never submits an order.
- Actual LIVE Auto-Trade start still requires platform/operator checklist gates.
- Real order placement remains guarded by existing risk/execution layers.
- Paper deposits/trades/PnL are not migrated into live ledger truth.

## Validation
- `python3 -m py_compile` on touched runtime Python files: PASS.
- `python3 -m ruff check` on touched runtime/test Python files: PASS.
- Targeted pytest: 63 passed / 1 warning.
- Secret scan by diff review: no secrets or secret-like values added.
- UTF-8/mojibake scan: PASS.

## Files Changed
- projects/polymarket/crusaderbot/domain/activation/live_mode.py
- projects/polymarket/crusaderbot/domain/activation/live_checklist.py
- projects/polymarket/crusaderbot/bot/handlers/activation.py
- projects/polymarket/crusaderbot/bot/handlers/mvp/_users.py
- projects/polymarket/crusaderbot/bot/handlers/mvp/autotrade.py
- projects/polymarket/crusaderbot/webtrader/backend/router.py
- projects/polymarket/crusaderbot/webtrader/backend/schemas.py
- projects/polymarket/crusaderbot/tests/test_self_serve_live_mode.py
- projects/polymarket/crusaderbot/tests/test_live_checklist.py
- projects/polymarket/crusaderbot/tests/test_activation_handlers.py
- projects/polymarket/crusaderbot/tests/test_live_activation_flow.py
- projects/polymarket/crusaderbot/tests/test_telegram_live_truth.py
- projects/polymarket/crusaderbot/tests/test_totp_2fa.py

## Next Gate
WARP🔹CMD first-pass PR check, then WARP•R00T finishing pass or WARP•SENTINEL approval/conditional approval because this is MAJOR live activation / capital-path gate work.

---

## WARP•R00T Finishing Pass (PR #1784)

Last Updated : 2026-06-12 21:30
Decision     : APPROVE — WARP•R00T takes final gate responsibility, self-merge on CI green. WARP•SENTINEL did NOT run and is not claimed.

### CMD first-pass blockers — disposition
- BLOCKER 1 (dirty / behind main) — RESOLVED. Merged latest `origin/main` into the head branch; the only conflict was `state/PROJECT_STATE.md`, resolved by taking the merged #1783 AGENTS.md-compliant shape (per CMD "do not overwrite the corrected state shape") and re-applying the self-serve lane truthfully. `CHANGELOG.md` auto-merged.
- BLOCKER 2 (WebTrader `/autotrade/toggle` bypassed the LIVE $5/checklist gate) — FIXED. The toggle previously armed `users.auto_trade_on` after only a kill-switch + active-preset check. Root cause: the live arming gate was duplicated inline in the Telegram + MVP surfaces and simply absent from the WebTrader API. Fix: extracted ONE shared guard `domain/activation/live_mode.evaluate_live_autotrade_start(user_id, *, trading_mode=None, conn=None) -> LiveAutotradeStartGate` and routed all three arming paths through it. The guard: paper users pass through (no-op allow, existing behaviour intact); live users must clear the required `live_checklist` gates AND hold >= $5 confirmed available live USDC.e (checklist refusal takes precedence over funding). WebTrader toggle now refuses with HTTP 409 (`live_no_funds` / checklist) BEFORE any `auto_trade_on` write; kill-switch + active-preset checks retained.
- BLOCKER 3 (branch traceability drift) — FIXED. Exact PR head branch `warp/implement-self-serve-paper-to-live-switch` now used across this report, PROJECT_STATE, WORKTODO, CHANGELOG, and the PR body.
- BLOCKER 4 (PROJECT_STATE overclaim) — FIXED. State now sits on the merged #1783 shape; the self-serve lane reads as R00T-FINISHED MERGED #1784 under WARP•R00T final-gate authority (the entry only lands on main when actually merged on CI green).
- BLOCKER 5 (no CI on head) — RESOLVED on the finished head: full local suite 3487 passed + GitHub `Lint + Test` confirmed green before merge.

### Additional R00T fix (pre-existing CI red, not in CMD list)
- `tests/test_live_mode_truth.py::test_mode_writers_keep_both_columns_in_sync_and_auto_stop` was RED on the FORGE head: it pinned the ENABLE both-columns-in-sync write inline in `router.py`, but the self-serve refactor correctly centralized that write into `live_mode.enable_live_self_serve`. Relocated the assertion to the helper (enable) while keeping the disable-path assertion on the router — safety intent (both columns in sync + auto-stop on every mode write) preserved, not weakened.

### Files modified by the finishing pass (on top of FORGE)
- projects/polymarket/crusaderbot/domain/activation/live_mode.py (shared `evaluate_live_autotrade_start` guard + `LiveAutotradeStartGate`)
- projects/polymarket/crusaderbot/webtrader/backend/router.py (`/autotrade/toggle` LIVE arming gate)
- projects/polymarket/crusaderbot/bot/handlers/activation.py (delegate to shared guard)
- projects/polymarket/crusaderbot/bot/handlers/mvp/autotrade.py (delegate to shared guard)
- projects/polymarket/crusaderbot/tests/test_self_serve_live_mode.py (+5 guard unit tests)
- projects/polymarket/crusaderbot/tests/test_live_activation_flow.py (+4 WebTrader toggle gate tests)
- projects/polymarket/crusaderbot/tests/test_live_mode_truth.py (relocated stale enable-pin)
- state/PROJECT_STATE.md, state/WORKTODO.md, state/CHANGELOG.md (repo-truth sync)

### Validation (finishing pass)
- Full suite: `pytest projects/polymarket/crusaderbot/tests/` → 3487 passed, 11 skipped.
- ruff + py_compile on touched files: PASS.
- Secret-pattern scan + UTF-8/mojibake + BOM scan on touched files: clean.

### Inviolable invariants — confirmed clean
No flip of `USE_REAL_CLOB` / `EXECUTION_PATH_VALIDATED` / `ENABLE_LIVE_TRADING` / `CAPITAL_MODE_CONFIRMED`; no risk-constant or Kelly change; no hardcoded secrets; no real fund movement; asyncio only; 2FA stays optional and admin approval not required for the LIVE switch.
