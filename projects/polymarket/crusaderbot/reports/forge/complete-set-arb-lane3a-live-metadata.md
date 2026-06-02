# Complete-Set Arbitrage — Lane 3A (live position strategy_metadata)

**Branch:** `WARP/ROOT/complete-set-arb-lane3a-live-metadata`
**Role:** WARP•R00T (owner-directed: "Lane 3 complete" — phased 3A → 3B → 3C)
**Validation Tier:** STANDARD (additive metadata write on the live path; no change to
order submission, guards, risk, or capital flow)
**Claim Level:** FOUNDATION (pre-LIVE blocker; the live execution primitive is Lane 3B)

> Lane 3 (LIVE two-leg) is built in phases, each behind the default-OFF activation
> guards. **This PR = Lane 3A: the pre-LIVE blocker** — the live position INSERT
> did not persist `strategy_metadata`, so a live complete-set leg would carry no
> quote snapshot or pairing context. 3A fixes that for the existing single-leg
> live path AND unblocks the Lane 3B live booking primitive.

## 1. What was built

`domain/execution/live.py` `execute()`:
- New keyword param `strategy_metadata: dict | None = None`.
- The `INSERT INTO positions` now includes the `strategy_metadata` column
  (`$11::jsonb`), written as `json.dumps(strategy_metadata)` or `NULL` — mirroring
  the paper path (`paper.py:62-70`). The column has existed since migration 076;
  only the live writer was missing it.
- Added `import json`.

`domain/execution/router.py`:
- The `live_engine.execute(...)` call now forwards `strategy_metadata=strategy_metadata`
  (the router already received it and passed it to the paper path; only the live
  branch dropped it).

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

38 tests pass in `test_live_execution_rewire.py` (36 existing + 2 new:
`test_metadata_passed_to_position_insert` pins the column + `$11::jsonb` + the
json-encoded value reaching the INSERT; `test_none_metadata_inserts_null` pins the
NULL path). ruff + py_compile clean. All other live tests unaffected.

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

- **Validation Tier:** STANDARD
- **Claim Level:** FOUNDATION
- **Validation Target:** live position INSERT persists strategy_metadata (single-leg + future complete-set)
- **Not in Scope:** live order submission, two-leg execution, naked-leg unwind — Lane 3B/3C
- **Suggested Next Step:** WARP🔹CMD review → merge; then Lane 3B (live primitive, SENTINEL).
