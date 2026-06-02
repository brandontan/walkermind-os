# Complete-Set Arbitrage — Lane 2A (pair foundation + Lane 2 design)

**Branch:** `WARP/ROOT/complete-set-arb-lane2`
**Role:** WARP•R00T (owner-directed: "full two-leg execution")
**Validation Tier:** MAJOR (trading-core foundation; positions schema)
**Claim Level:** FOUNDATION (schema + design only — no execution wiring this PR)

> Lane 1 (merged #1557) shipped the pure detection/sizing core
> (`fillable_complete_set`). Lane 2 wires a PAPER two-leg execution path on top.
> Because this is the highest-risk pre-LIVE change, Lane 2 is split into safe
> sub-PRs. **This PR = Lane 2A: the schema link (migration 078) + the committed
> architecture for the rest of Lane 2.** No execution/scan/gate code changes yet.

---

## 1. What was built

- **Migration 078** — `positions.paired_position_id UUID REFERENCES positions(id)
  ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED`, nullable, + partial index
  `idx_positions_paired`. Links the two legs of a complete set so the
  engine/gate/exit/UI treat them as one unit. Additive: NULL for every existing
  row and every directional position → zero behaviour change until Lane 2B writes
  it. The FK is **deferrable** because the legs reference each other — deferring
  validation to COMMIT lets Lane 2B insert both rows already cross-linked in one
  transaction (no insert-then-update dance, no ordering footgun); directional
  inserts set NULL so the deferral never affects them.
- This design document (the Lane 2 architecture + sub-lane plan below).

## 2. Lane 2 architecture (the full design — implemented across 2A→2C)

**The unit.** A complete set = two `positions` rows (one `side='yes'`, one
`side='no'`) for the same `market_id`, cross-linked via `paired_position_id`.
Combined entry cost < $1.00/share (the Lane-1 quote); held to resolution where
one leg redeems $1.00 and the other $0.00 → locked `shares * (1.00 - avg_pair_cost)`.

**Pipeline boundary (target):**
```
DATA -> [SIGNAL: fillable_complete_set (Lane 1)] -> RISK (set-aware) -> EXECUTION (two-leg PAPER) -> redeem
```

**Booking (Lane 2B).** A new `domain/execution/complete_set_exec.py`
`book_complete_set_paper(...)` mirrors `paper.execute` (`paper.py:22`) but inside
ONE `conn.transaction()` inserts: 2 orders (filled), 2 `positions` rows
cross-linked via `paired_position_id` (the mig-078 deferrable FK validates the
mutual links at commit), and debits the ledger for each leg's cost. `strategy_type="complete_set_arb"`; `strategy_metadata` carries the quote
snapshot (avg_pair_cost, net_margin, sibling token ids). No mid-trade TP/SL — the
exit is settlement (Exit via the existing redeem path), so `tp_pct`/`sl_pct` stay
NULL and the exit watcher treats a paired position as hold-to-resolution. Kept in
a separate module (not `paper.py`) to isolate the new primitive and keep the
single-leg path untouched — it is NOT a shim (distinct trade type, distinct call).

**Risk gate re-scope (Lane 2C).** A complete set must count as **one** unit, with
exposure = the set cost (≈ `shares * avg_pair_cost`), NOT 2× a leg notional:
- Step 7 (`gate.py:344` `max_concurrent`): a set is 1 concurrent position, not 2.
- Step 8 (`gate.py:360` correlated exposure): the YES and NO legs are perfectly
  anti-correlated (one always wins) — booking both is risk-REDUCING, so the pair
  must not be double-counted as 2× directional exposure.
- Approach: gate the SET once on its combined cost before booking, then book both
  legs atomically (legs are not re-gated individually). A set-aware `GateContext`
  flag (e.g. `complete_set=True`) keeps the directional path byte-for-byte
  unchanged. Kelly/per-trade caps still bound the combined size.

**Scan/registry/preset wiring (Lane 2C).** Complete-set detection does not fit
`BaseStrategy`/`SignalCandidate` (a set has no single `side`; `VALID_SIDES =
("YES","NO")`), so it runs as a dedicated scan branch that, when enabled, fetches
both books for a candidate market, calls `fillable_complete_set`, gates the set,
and calls `book_complete_set_paper`. Gated behind a **default-OFF** feature flag
(`COMPLETE_SET_ARB_ENABLED=False`) + a preset/operator surface. Frequency is rare
(MM vig) and edge is UNMEASURED (WARP-51 F-1) — 2C must LOG live fillable quotes
before any capital scaling, and LIVE stays Lane 3 (owner-gated + SENTINEL).

**Exit (reuse).** Hold-to-resolution → the existing CTF redeem path settles both
index sets; no new exit engine. The exit watcher must skip mid-trade TP/SL for
paired positions (no `force_exit`, no stop) — verified/added in 2C.

## 3. Files created / modified (this PR)

- `projects/polymarket/crusaderbot/migrations/078_positions_paired_position_id.sql` (new)
- `projects/polymarket/crusaderbot/reports/forge/complete-set-arb-lane2.md` (new)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` (NEXT PRIORITY + sub-lane plan)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` (append)

## 4. What is working

- Migration is additive + idempotent (`ADD COLUMN IF NOT EXISTS`, `CREATE INDEX
  IF NOT EXISTS`); `ON DELETE SET NULL` prevents any sibling-cascade delete.
- No runtime code touched → existing suite unaffected (schema-only + docs).

## 5. Known issues / scope boundaries

- **Not applied to Supabase yet.** Migration file only; applying 078 to prod is a
  gated operator step (same convention as migs 075/076), done when Lane 2B lands.
- **No execution/gate/scan change this PR.** `paired_position_id` is written by
  nothing until Lane 2B → the column is inert.
- Edge is rare + UNMEASURED — Lane 2C logs live quotes before capital.

## 6. What is next

- **Lane 2B (MAJOR, PAPER):** `complete_set_exec.book_complete_set_paper` +
  hermetic tests (fake conn) — atomic two-leg booking, cross-link, dual ledger
  debit. Still unwired into scan.
- **Lane 2C (MAJOR, PAPER):** gate step 7/8 set re-scope + scan branch + registry/
  preset + `COMPLETE_SET_ARB_ENABLED` default-OFF flag + exit-watcher paired-skip
  + live-quote logging.
- **Lane 3 (MAJOR, owner-gated + SENTINEL):** LIVE two-leg FOK + naked-leg
  fallback + idempotent recovery; depends on the tracked `live.py`
  `strategy_metadata` follow-up.

---

- **Validation Tier:** MAJOR
- **Claim Level:** FOUNDATION
- **Validation Target:** migration 078 additivity + the committed Lane 2 design
- **Not in Scope:** booking primitive, gate re-scope, scan/preset wiring, exit
  handling, LIVE — all Lane 2B/2C/3
- **Suggested Next Step:** WARP🔹CMD review of the design + migration; then Lane 2B
  (booking primitive + tests) as the next branch.
