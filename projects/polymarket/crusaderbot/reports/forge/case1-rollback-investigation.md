# WARP•FORGE — case1-rollback-investigation (REPORT ONLY, no code change)

Validation Tier: MINOR (investigation report; no runtime change)
Claim Level: FOUNDATION
Scope: Why `test_case1_closing_rollback_on_cancelled_sell` returned `rolled_back=0` (`pending=1`) in the all-broker staging run (27026102440), and whether that is a code bug or correct safety behavior.

## Verdict

**Correct safety behavior — NOT a code bug.** The failure is a **test-timing gap**, mirroring exactly why case3 needed `_poll_open_order`.

## Evidence

1. The test (`tests/staging/test_live_reconcile_staging.py:589-603`) does:
   - `close_id = await _place_resting_buy(broker)` — place a resting GTC as the stand-in close order.
   - `await broker.cancel_order(close_id)` — cancel it.
   - immediately `await lr.reconcile_closing_positions(...)` and assert `res["rolled_back"] == 1`.
   No wait/poll between the cancel and the reconcile.

2. The run logged: `live_reconcile_closing_sweep closed=0 error=0 paged_no_id=0 paged_partial_close=0 pending=1 rolled_back=0 scanned=1`. So the order was classified **pending**, not error and not rolled-back.

3. `reconcile_closing_positions` (`domain/execution/live_reconcile.py:465-493`):
   ```
   broker = await client.get_order(close_order_id)
   fills  = await client.get_fills(close_order_id)
   st = _fill_status(broker)
   ...
   if st not in (FILL_FILLED, FILL_KILLED):
       ... return "pending"        # Only act on a TERMINAL broker state
   ```
   The code is explicitly designed (lines 482-486) to act **only on a terminal broker state** and otherwise leave the position `closing` for the next sweep — "the next sweep re-checks once the order settles."

4. `_fill_status` (`domain/execution/complete_set_exec.py:96-115`) maps to `FILL_KILLED` for `_KILLED_STATUSES = {unmatched, killed, kill, cancelled, canceled, expired, rejected, failed}` — a comprehensive terminal-cancel set. So if `get_order` had returned a `CANCELED`-class status, the sweep WOULD have rolled back. Because it returned `pending`, `get_order` must have returned a **non-terminal** status (e.g. `LIVE`) — i.e. the cancellation had not yet propagated to Polymarket's eventually-consistent `/data/order` read at the instant of the immediate post-cancel reconcile (read-after-write lag).

5. This is the SAME eventual-consistency property that forced case3 to use `_poll_open_order` (bounded poll until the order leaves the book). case1 has no equivalent poll, so a single immediate reconcile legitimately observes the order still-live → conservative `pending`.

## Why this is the safe outcome

Returning `pending` when the close order is not yet confirmed terminal is the correct, conservative design: the system never rolls a position back to `open` (which would re-arm the exit watcher) on an unconfirmed cancel, and never finalizes a close it cannot verify. The in-memory DB fake the test mounts is synchronous, so against the fake the cancel is "instantly terminal" and the assert passes; against the real broker the cancel is eventually-consistent, so the immediate assert is too strict.

## Recommendation (CMD decides — no code change made)

- **Test-side fix (preferred, no prod change):** add a bounded poll in `test_case1_closing_rollback_on_cancelled_sell` that re-runs `reconcile_closing_positions` until `rolled_back == 1` (or a timeout), mirroring `_poll_open_order` — i.e. wait for the cancel to reach a terminal `get_order` state before asserting. This validates the real-broker rollback path without weakening the conservative production semantics.
- **No production change recommended.** `reconcile_closing_positions` + `_fill_status` already handle the terminal `CANCELED` status correctly; the deferral on a not-yet-terminal read is intended.
- Optional hardening (low ROI): add a one-shot DIAG of the `get_order` status in the case1 test so a future run distinguishes "lag (LIVE)" from any unmapped status with certainty.

## Not in scope

No edit to `live_reconcile.py`, `complete_set_exec.py`, or the case1 test in this lane — report only, per directive item (3). CMD to decide whether to apply the test-side poll.
