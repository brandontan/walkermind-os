# WARP•FORGE Report — self-serve-paper-to-live-switch

Last Updated : 2026-06-12 20:42
Project      : CrusaderBot
Project Root : projects/polymarket/crusaderbot
Branch       : WARP/self-serve-paper-to-live-switch
Issue        : #1782
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
