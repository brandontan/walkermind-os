# WARP•FORGE Report — live-switch-notification-isolation-fix

Last Updated : 2026-06-12 16:55 UTC
Project      : CrusaderBot
Project Root : projects/polymarket/crusaderbot
Branch       : warp/fix-live-switch-notification-isolation
PR           : #1794
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

---

## WARP•R00T Finishing Pass (PR #1794)

Last Updated : 2026-06-12 16:55 UTC
Decision     : APPROVE — WARP•R00T takes final gate responsibility, self-merge on CI green. WARP•SENTINEL did NOT run and is not claimed.

### CMD Blocker 1 — scope expanded to FULL paper-session reset (the load-bearing fix)
The FORGE diff only isolated NOTIFICATIONS. The owner reproduced a deeper defect: PAPER -> LIVE -> PAPER still showed the old paper bankroll (`904.16 USDC`) and stale paper activity (`paper close resolution_loss`, `paper open yes`, ...). Root cause (mapped against the code):
- Paper balance is DERIVED: `paper_balance = wallets.balance_usdc - get_live_balance()`. `wallets.balance_usdc` is a stored column that accumulates paper PnL; archiving positions/orders never reset it, so it stayed at the stale value.
- The `ledger` table has NO mode column — a paper row is simply "not a live row". Archiving positions to `paper_archived` did NOT remove the paper ledger rows from the paper wallet feed.
- `/activity` and `/orders` had NO mode filter at all, so they returned `paper_archived` rows after a switch.

R00T fix:
- New migration `098_ledger_archived.sql`: additive, idempotent `ledger.archived BOOLEAN NOT NULL DEFAULT FALSE` + partial index. Live rows are never archived (they fail the paper predicate), so the live bucket / `get_live_balance` is unaffected.
- `domain/activation/live_mode.enable_live_self_serve` (only on a genuine PAPER -> LIVE transition, `from_mode != 'live'`) now also: archives the user's active paper ledger rows (`UPDATE ledger SET archived=TRUE WHERE ... AND NOT <live_filter>`, retained for audit — never deleted); resets the paper bankroll by setting `wallets.balance_usdc = $1,000 + live_balance` (preserving the live component of the mixed bucket by construction); and seeds a fresh non-archived paper `deposit` row so the returning paper feed opens on a clean $1,000. New result fields `archived_ledger_rows` / `paper_session_reset` / `paper_balance_after_reset_usdc` audited in the enable payload.
- Read isolation: `/activity` and `/orders` are now mode-scoped (`p.mode`/`o.mode = current mode`), excluding `paper_archived`; `/wallet` and `/wallet/ledger` add `AND NOT l.archived`. The live balance/feeds are unchanged (live ledger rows are never archived).
- Net effect: PAPER -> LIVE archives the entire paper session (positions, orders, ledger, alerts) and seeds a fresh $1,000 practice bankroll; returning to PAPER shows a clean session, and no PAPER row ever enters LIVE accounting/history/balance.

### CMD Blocker 5 + R00T hardening — pre-existing CI red & alert coverage
- CI red was 2 stale `SimpleNamespace` switch mocks in `test_live_activation_flow.py` missing the FORGE-added `archived_notifications` field — updated (and extended with the new reset fields).
- Hardening (unmodeled alert rows): the `/alerts` mode filter lets user rows with empty `metadata.mode` pass, but the switch-time `dismissed=TRUE` UPDATE has NO metadata predicate (keyed on `user_id` + `dismissed=FALSE` + `created_at<=NOW()`), so legacy unmodeled paper rows are also dismissed. Pinned by `test_switch_dismisses_unmodeled_paper_alert_rows`. The dismiss is bounded to `created_at<=NOW()` so a LIVE-context alert created during/after the switch txn is not dismissed.

### CMD Blockers 2/3/4 — repo-truth + PR body
Exact PR head branch `warp/fix-live-switch-notification-isolation` across report/state/worktodo/changelog/PR body; PROJECT_STATE lane moved off premature `[COMPLETED]` BUILT-only wording to the R00T-finished merged truth; PR body rewritten to code truth + gate summary.

### Validation (finishing pass)
- Full suite: `pytest projects/polymarket/crusaderbot/tests/` -> 3508 passed, 11 skipped.
- ruff + py_compile clean on touched Python; migration 098 SQL: no BOM, idempotent.
- New/updated tests: paper-ledger archive + bankroll reseed behaviour, `from_mode='live'` no-reset guard, migration 098 pin, `/activity` + `/orders` mode-scope pins, wallet-feed `NOT archived` pins, unmodeled-alert dismissal pin.
- Secret-pattern + UTF-8/mojibake/BOM scans clean.

### Inviolable invariants — confirmed clean
No `USE_REAL_CLOB` / `EXECUTION_PATH_VALIDATED` / `ENABLE_LIVE_TRADING` / `CAPITAL_MODE_CONFIRMED` flip; the bankroll reset is PAPER money only (no real fund movement — live balance is derived from untouched live ledger rows); shared `$5` live Auto-Trade start guard + Auto-Trade-OFF-on-switch unchanged; 2FA optional; asyncio only.
