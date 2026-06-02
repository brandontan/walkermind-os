# Complete-Set Arbitrage — Lane 2C-2a (exit-watcher paired-skip)

**Branch:** `WARP/ROOT/complete-set-arb-lane2c-exit`
**Role:** WARP•R00T (owner-directed: "full two-leg execution")
**Validation Tier:** MAJOR (exit path)
**Claim Level:** FOUNDATION (defensive hold rule; booking arrives in Lane 2C-2b)

> Lane 2C-2 is the runtime activation; it is split so each sensitive surface lands
> in its own reviewable PR. **This PR = Lane 2C-2a: the exit-watcher hold rule for
> complete-set positions.** It lands the protection BEFORE the booking that needs
> it (Lane 2C-2b), so the moment a set is booked the watcher already holds it to
> resolution.

## 1. What was built

`domain/execution/exit_watcher.py` `evaluate()` — a complete-set leg
(`strategy_type == "complete_set_arb"`) now returns **hold** (no exit) before the
TP/SL/strategy/horizon checks. Inserted right after the `force_close_intent`
branch and after the top-of-function `market_resolved` branch, so a set can only
close via:
- **force_close_intent** (emergency Pause+Close-All — user-initiated), or
- **market_resolved** (settlement via the redemption pipeline).

It never closes on mid-trade TP/SL, a strategy hook, or the resolution-horizon
guard — any of which would close one leg and strand the opposite leg as a naked
directional bet, destroying the hedge that makes the arb riskless.

`run_once()` has two expiry paths that bypass `evaluate()` entirely; both now
skip complete-set legs:
- **Phase A (None-price → MARKET_EXPIRED):** after `_EXPIRED_TICK_THRESHOLD`
  consecutive None-price ticks on an actually-expired market, a directional
  position is closed as expired. A complete_set leg instead pins its fail
  counter and holds (no `close_as_expired`).
- **Phase B (resolved-market sweep):** the losing leg of a resolved market is
  normally closed as expired. A complete_set leg is counted as held and left
  for the redemption pipeline.

Both expiry paths call `registry.close_as_expired`, which **refunds `size_usdc`
to the wallet** — correct for a directional bet, but for a set it would refund
the stake instead of letting the hedge settle (winning leg → $1, losing leg →
$0 via redemption), silently inflating PnL. The skip closes that gap.

## 2. Why this ordering

A complete set's locked margin is only realised at settlement (one leg → $1, the
other → $0). The two legs are anti-correlated; closing one mid-trade converts a
hedged, riskless pair into an unhedged directional position. So the only valid
exits are settlement (redemption) and an explicit operator emergency unwind —
both preserved. Landing this before Lane 2C-2b means no window exists where a
booked set could be wrongly TP/SL-closed.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/domain/execution/exit_watcher.py` (paired-skip)
- `projects/polymarket/crusaderbot/tests/test_exit_watcher.py` (3 tests + `dataclasses` import)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

56 exit-watcher tests pass (51 existing + 5 new): a set holds through a crossed TP
threshold, holds through a crossed SL threshold, STILL force-closes on
`force_close_intent`, is NOT expired on a 3-tick None price (Phase A), and is NOT
expired on a resolved-market sweep (Phase B). ruff + py_compile clean. The skip
keys on `OpenPositionForExit.strategy_type` (populated at `registry.py:230`).

## 5. Known issues / scope boundaries

- **Defensive / inert today:** nothing books a `complete_set_arb` position yet
  (Lane 2C-2b), so the new branch is exercised only by tests until then. It
  changes nothing for directional positions (guarded by an exact strategy_type
  equality).
- Horizon/strategy exits for sets are intentionally skipped (held to resolution);
  a far-dated set holds its concurrency slot by design — bounded by the
  default-OFF flag + the rare/UNMEASURED edge (logged before any capital in 2C-2b).

## 6. What is next

- **Lane 2C-2b (MAJOR, PAPER):** the scan branch — `GateContext.complete_set`
  flag (gated once on combined cost, side-specific checks skipped) + a dedicated
  complete-set scan branch (fetch both books via `get_book` →
  `fillable_complete_set` → gate → `book_complete_set_paper`) behind
  `COMPLETE_SET_ARB_ENABLED` (default OFF) + live-quote logging. Apply migration
  078 to Supabase with it.
- **Lane 3 (MAJOR, owner-gated + SENTINEL):** LIVE two-leg.

---

- **Validation Tier:** MAJOR
- **Claim Level:** FOUNDATION
- **Validation Target:** exit-watcher hold rule for complete_set_arb positions
- **Not in Scope:** scan branch, gate flag, booking call, LIVE — Lane 2C-2b / Lane 3
- **Suggested Next Step:** WARP🔹CMD/SENTINEL review; then Lane 2C-2b (scan wiring).
