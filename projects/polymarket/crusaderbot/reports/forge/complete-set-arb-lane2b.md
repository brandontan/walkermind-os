# Complete-Set Arbitrage — Lane 2B (PAPER booking primitive)

**Branch:** `WARP/ROOT/complete-set-arb-lane2b`
**Role:** WARP•R00T (owner-directed: "full two-leg execution")
**Validation Tier:** MAJOR (trading-core execution path)
**Claim Level:** FOUNDATION (booking primitive, shipped UNWIRED into scan)

> Lane 2A (merged) added the `paired_position_id` deferrable FK (mig 078). Lane 2B
> adds the PAPER two-leg booking primitive that writes a linked pair. Still
> UNWIRED — no scan/gate/preset calls it yet (that is Lane 2C) — so runtime risk
> stays zero while the transaction shape is proven by hermetic tests.

## 1. What was built

`domain/execution/complete_set_exec.py` — `book_complete_set_paper(...)`:
consumes a Lane-1 `CompleteSetQuote` and, in ONE `conn.transaction()`:
- inserts 2 filled paper **orders** (YES + NO), each with a per-leg idempotency
  key (`{key}:yes` / `{key}:no`) derived from one base identity;
- inserts 2 open paper **positions** (one per side), per-share price =
  leg_cost / fillable_shares, **no TP/SL** (held to settlement);
- **cross-links** them via `paired_position_id` (both directions; the mig-078
  deferrable FK validates at COMMIT);
- **debits the ledger** once per leg (`T_TRADE_OPEN`, ref = each position id);
- best-effort `audit.write` post-commit (wrapped — never unwinds a booked set).

Guards:
- **Duplicate set** (both keys already seen) → `{"status":"duplicate"}`, nothing written.
- **Partial idempotency** (exactly one leg fresh = a half set) → raises
  `RuntimeError` so the transaction rolls back; a half pair never persists.
- **Non-positive shares** → `{"status":"skipped"}` before any DB call.

Quote snapshot (`complete_set`, `condition_id`, token ids, `avg_pair_cost`,
`net_margin_usdc`, …) rides both legs in `strategy_metadata` for exit/UI replay.

## 2. Architecture fit

A dedicated primitive (not `paper.execute`) because a set is ONE unit of TWO
mutually-referencing rows with a single idempotency identity and no mid-trade
exit — which `paper.execute` (single directional side) cannot express. It mirrors
`paper.execute`'s order/position INSERT + ledger pattern exactly, so behaviour is
consistent with the directional path. Lane 2C gates the set once on combined cost
(re-scoped steps 7/8) and calls this from a scan branch behind a default-OFF flag.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/domain/execution/complete_set_exec.py` (new)
- `projects/polymarket/crusaderbot/tests/test_complete_set_exec.py` (new)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` (NEXT PRIORITY → Lane 2C)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` (append)

## 4. What is working

7/7 hermetic tests pass (fake conn), ruff + py_compile clean:
happy-path two-leg link, per-leg idempotency keys, per-leg pricing + no-TP/SL,
metadata snapshot on both legs, duplicate-set books-nothing, partial-idempotency
raises-to-rollback, non-positive-shares skipped. Grep confirms zero callers →
genuinely unwired.

## 5. Known issues / scope boundaries

- **Unwired by design.** No scan/gate/registry/preset calls it; migration 078
  not yet applied to Supabase (applied when Lane 2C lands and the path goes live
  in PAPER).
- **No risk gate yet.** The set-aware gate (steps 7/8 re-scope) is Lane 2C; until
  then nothing sizes/limits a set.
- **No telegram notify yet** — set-level notification + preset wiring is Lane 2C
  (needs preset/notification context).
- Edge rare (MM vig) + UNMEASURED — Lane 2C logs live quotes before any capital.

## 6. What is next

- **Lane 2C (MAJOR, PAPER):** set-aware risk gate (step 7 = 1 unit, step 8 =
  combined cost, YES/NO anti-correlated) + dedicated scan branch fetching both
  books + `fillable_complete_set` + this primitive + registry/preset surface +
  `COMPLETE_SET_ARB_ENABLED` default-OFF flag + exit-watcher paired-skip +
  live-quote logging. Apply migration 078 to Supabase with this lane.
- **Lane 3 (MAJOR, owner-gated + SENTINEL):** LIVE two-leg FOK + naked-leg
  fallback + idempotent recovery; depends on the `live.py` strategy_metadata
  follow-up.

---

- **Validation Tier:** MAJOR
- **Claim Level:** FOUNDATION
- **Validation Target:** the two-leg PAPER booking transaction + its guards in isolation
- **Not in Scope:** risk gate, scan/registry/preset wiring, flag, exit handling,
  telegram notify, LIVE — all Lane 2C / Lane 3
- **Suggested Next Step:** WARP🔹CMD review; then Lane 2C (gate re-scope + scan
  wiring + default-OFF flag) as the next branch.
