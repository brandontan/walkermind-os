# WARP•FORGE Report — live-switch-notification-isolation-fix

Last Updated : 2026-06-12 23:19
Project      : CrusaderBot
Project Root : projects/polymarket/crusaderbot
Branch       : WARP/live-switch-notification-isolation-fix
Tier         : MAJOR
Claim Level  : NARROW INTEGRATION
Issue        : #1792

## Objective
Fix PAPER -> LIVE notification isolation so a user entering LIVE starts with a clean user-facing notification context. PAPER trade/activity notification records must not appear in the LIVE AlertCenter or count as LIVE unread items, while audit-important records remain retained.

## Implementation
- `domain/activation/live_mode.py` now archives pre-switch per-user `system_alerts` rows by setting `dismissed=TRUE` inside the same transaction that flips `user_settings.trading_mode='live'`, forces `users.auto_trade_on=FALSE`, archives paper positions/orders, and writes `alerts_ack_at=NOW()`. Rows are not deleted.
- `webtrader/backend/router.py` keeps the existing `alerts_ack_at` server-side watermark and adds mode-bucket filtering for user-scoped structured alerts: alerts with `metadata.mode` must match the current `user_settings.trading_mode`; broadcast rows and unmodeled rows remain governed by existing scope/watermark rules.
- `webtrader/frontend/src/App.tsx` now reacts to `settings` SSE by clearing in-memory AlertCenter rows, resetting offset, refetching alerts, and refreshing the TopBar trading-mode pill. This prevents stale PAPER alerts/unread counts from surviving after the backend switch commits.
- `jobs/daily_pnl_summary.py` tags daily report web mirrors as `metadata={"mode": "paper"}`.
- `services/notification_service.py` adds structured `mode` metadata for event-bus trade opened/closed/copy-trade web mirrors so future query filtering has a reliable bucket.

## Validation performed
- `python -m py_compile` on touched Python runtime files.
- Targeted pytest: `test_self_serve_live_mode.py`, `test_notification_prefs.py`, and new `test_live_switch_notification_isolation.py` — 26 passed.
- Frontend build after dependency install: `npm run build` — pass.

## Invariants preserved
- No strategy rewrite.
- No risk model redesign.
- No real fund movement or live-fire validation.
- No Auto-Trade behavior change except preserving the existing forced-OFF switch behavior.
- No flips to `USE_REAL_CLOB`, `EXECUTION_PATH_VALIDATED`, `ENABLE_LIVE_TRADING`, or `CAPITAL_MODE_CONFIRMED`.
- Existing paper position/order archive behavior remains intact.
- LIVE Auto-Trade start guard remains the shared required-checklist + confirmed available live USDC.e >= $5 path.
- 2FA remains optional/recommended for account and withdrawal protection.

## Next gate
WARP🔹CMD first-pass PR check, then WARP•R00T final gate responsibility or WARP•SENTINEL approval before merge because this is MAJOR live activation / paper-live isolation work.
