# WARP•FORGE Report — Force Redeem + awaiting-redeem state + settlement snapshot

- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Validation Target: the `awaiting_redeem` flag on the positions API, the new force-redeem endpoint, and the portfolio-snapshot write on resolution settlement.
- Not in Scope: settlement math (unchanged); auto-redeem mode semantics (hourly vs instant preserved); the frontend (separate PR — Home open-positions + realtime SSE + the Force Redeem button UI).
- Suggested Next Step: WARP•SENTINEL validation, then the frontend PR consumes `awaiting_redeem` + calls the endpoint.

---

## 1. What was built

Owner report: a won Close Sweep position sat "open / stuck not closed". Diagnosed: it
is a winner (market resolved in its favour) whose owner uses `auto_redeem_mode='hourly'`,
so it waits in `redeem_queue` up to an hour. Per owner direction we keep the hourly
setting but make the state visible + manually actionable (no auto-flip to instant):

1. **`awaiting_redeem`** (new `PositionItem` field): true when a position is still
   `open` AND its market `resolved` with `winning_side == side`. The UI uses it to show
   "waiting hourly redeem" instead of a stale "open @ price".
2. **Force Redeem endpoint** `POST /api/web/positions/{id}/redeem`: runs the existing
   instant redeem fast-path (`instant_worker.try_process`) on the position's pending
   `redeem_queue` row so the user can settle now. User-scoped; 409 when there is no
   pending redemption (not won / already settling / already redeemed).
3. **Settlement snapshot**: `settle_winning_position` + `settle_losing_position` now
   call `portfolio_snapshots.write_snapshot(user_id)` (best-effort, like
   `paper.close_position`) so the `cb_portfolio` NOTIFY pushes the new equity/PnL to
   WebTrader SSE listeners the instant a candle settles (realtime fix groundwork).

## 2. Current system architecture

No settlement logic changed. The endpoint reuses `instant_worker.try_process` (the same
path instant-mode users already get). `awaiting_redeem` is a read-only derivation from
the positions+markets join. The snapshot write rides the existing
`portfolio_snapshots` → `trg_cb_portfolio_snapshots` → `cb_portfolio` NOTIFY → SSE
`portfolio` pipeline. `instant_worker.try_process` remains gated by
`AUTO_REDEEM_ENABLED` (now true) and is paper-safe (skips on-chain when mode != live).

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/webtrader/backend/schemas.py (PositionItem.awaiting_redeem)
- projects/polymarket/crusaderbot/webtrader/backend/router.py (positions query computes awaiting_redeem; new POST /positions/{id}/redeem)
- projects/polymarket/crusaderbot/services/redeem/redeem_router.py (write_snapshot in settle_winning_position + settle_losing_position; import)

Created:
- projects/polymarket/crusaderbot/tests/test_webtrader_positions.py

State:
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md
- projects/polymarket/crusaderbot/state/CHANGELOG.md

## 4. What is working

- Full suite: 1748 passed, 1 skipped (5 new). py_compile clean.
- New tests cover: awaiting_redeem true (open+resolved+winner) / false (loser) /
  false (unresolved); force-redeem runs instant_worker on a pending row; 409 when none.

## 5. Known issues

- The frontend Force Redeem button + "waiting redeem" label + realtime wiring land in
  the follow-up frontend PR; this PR only ships the backend contract.
- For instant-mode users the awaiting_redeem window is tiny (settles on the same tick),
  so the state mostly appears for hourly users — intended.

## 6. What is next

- WARP•SENTINEL validation, then Fly redeploy.
- Frontend PR: Home shows open positions (replacing the signal feed), Home+Portfolio
  subscribe to the full realtime SSE set (positions / position_updated / portfolio), and
  position cards render the awaiting-redeem state + a Force Redeem button calling this
  endpoint.
