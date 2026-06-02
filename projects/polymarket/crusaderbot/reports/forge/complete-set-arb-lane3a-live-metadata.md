# Complete-Set Arbitrage — Lane 3A (live position strategy_metadata)

**Branch:** `WARP/ROOT/complete-set-arb-lane3a-live-metadata`
**Role:** WARP•R00T (owner-directed: "Lane 3 complete" — phased 3A → 3B → 3C)
**Validation Tier:** MAJOR (modifies the live execution / order path — AGENTS.md
tier rule; WARP•SENTINEL required before merge, even though the change is additive)
**Claim Level:** FOUNDATION (pre-LIVE blocker; the live execution primitive is Lane 3B)

> Lane 3 (LIVE two-leg) is built in phases, each behind the default-OFF activation
> guards. **This PR = Lane 3A: the pre-LIVE blocker** — the live position INSERT
> did not persist `strategy_metadata`, so a live complete-set leg would carry no
> quote snapshot or pairing context. 3A fixes that for the existing single-leg
> live path AND unblocks the Lane 3B live booking primitive.

## 1. What was built

`domain/execution/live.py` `execute()`:
- New keyword params `active_preset: str | None = None` and
  `strategy_metadata: dict | None = None`.
- The `INSERT INTO positions` now includes `active_preset` (`$11`) and
  `strategy_metadata` (`$12::jsonb`) — exactly mirroring the paper path
  (`paper.py:58-70`). Both columns already exist (active_preset mig 062,
  strategy_metadata mig 076); only the live writer was missing them.
- Added `import json`.

`domain/execution/router.py`:
- The `live_engine.execute(...)` call now forwards `active_preset` AND
  `strategy_metadata` (the router already received both and passed them to the
  paper path; only the live branch dropped them).

Both omissions are the SAME class of pre-existing bug: live positions lacked the
per-position context paper positions carry. `active_preset` matters for safety —
`OpenPositionForExit.active_preset` (registry.py:233) drives the
close_sweep/safe_close/flip_hunter force-exits; a NULL on a live candle position
would silently skip its forced exit (flagged in review).

## 2. Why this is safe / in scope

- **Additive only.** No change to order submission, `assert_live_guards`, FOK/GTC
  handling, sizing, or ledger flow. A live position simply gains the metadata
  snapshot it should always have had.
- **Behind the 5 default-OFF guards** (`ENABLE_LIVE_TRADING` + 4 others) +
  `USE_REAL_CLOB` + `role=admin` + `trading_mode=live` — unchanged; the live path
  remains dead until an operator flips them.
- **No migration** — column exists (mig 076).

## 3. Files created / modified

- `projects/polymarket/crusaderbot/domain/execution/live.py` (param + INSERT + import)
- `projects/polymarket/crusaderbot/domain/execution/router.py` (forward strategy_metadata)
- `projects/polymarket/crusaderbot/tests/test_live_execution_rewire.py` (2 tests)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `CHANGELOG.md`

## 4. What is working

44 tests pass (`test_live_execution_rewire.py` + `test_candle_auto_router.py`):
2 new pin `active_preset` (`$11`) + `strategy_metadata` (`$12::jsonb`) reaching the
INSERT in order, and the NULL path for both. ruff + py_compile clean. All other
live + router tests unaffected.

## 5. Known issues / scope boundaries

- This lane does NOT submit any orders or change live behaviour — it only persists
  metadata. The complete-set live execution (two-leg FOK + naked-leg auto-unwind +
  idempotent recovery) is Lane 3B.

## 6. What is next

- **Lane 3B (MAJOR, WARP•SENTINEL):** `book_complete_set_live` — submit both legs
  FOK; on a one-leg-only fill, **auto-unwind** the naked leg (aggressive FOK sell to
  flatten; halt + operator alert if the unwind fails); idempotent crash recovery;
  cross-link via `paired_position_id`; `strategy_metadata` snapshot (now possible
  via 3A). Behind the activation guards.
- **Lane 3C:** route `complete_set_scan` `chosen_mode == "live"` to the live booker
  (currently skipped), behind `COMPLETE_SET_ARB_ENABLED` + the guards.

---

- **Validation Tier:** MAJOR (live execution/order path)
- **Claim Level:** FOUNDATION
- **Validation Target:** live position INSERT persists active_preset + strategy_metadata (single-leg + future complete-set)
- **Not in Scope:** live order submission, two-leg execution, naked-leg unwind — Lane 3B/3C
- **Suggested Next Step:** WARP•SENTINEL validation (MAJOR, live path) → owner merge; then Lane 3B.

### Validation Handoff (NEXT PRIORITY)

WARP•SENTINEL validation required for Lane 3A (live-path metadata persistence) before merge.
Source: projects/polymarket/crusaderbot/reports/forge/complete-set-arb-lane3a-live-metadata.md
Tier: MAJOR
