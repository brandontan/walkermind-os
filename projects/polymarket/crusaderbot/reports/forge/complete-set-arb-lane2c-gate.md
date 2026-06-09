# Complete-Set Arbitrage — Lane 2C-1 (risk-gate re-scope + kill switch)

**Branch:** `WARP/ROOT/complete-set-arb-lane2c-gate`
**Role:** WARP•R00T (owner-directed: "full two-leg execution")
**Validation Tier:** MAJOR (risk gate)
**Claim Level:** FOUNDATION (gate re-scope + flag; no scan wiring yet)

> Lane 2C is the wiring lane; it is split so the risk-gate change lands in its own
> small, reviewable PR. **This PR = Lane 2C-1: the set-aware concurrency re-scope
> + the default-OFF kill switch.** Built to be provably INERT until complete sets
> exist (which requires Lane 2C-2's scan branch + this flag ON).

## 1. What was built

- **`COMPLETE_SET_ARB_ENABLED: bool = False`** (`config.py`) — master kill switch
  for the complete-set scan + booking path. Default OFF; nothing scans or books a
  set until an operator flips it (Lane 2C-2 reads it).
- **Step-7 concurrency re-scope** (`domain/risk/gate.py` `_open_position_count`):
  counts a complete set (two `paired_position_id`-linked legs) as **ONE** unit,
  not two, so a set doesn't burn the concurrency budget at 2×. New SQL:
  `COUNT(DISTINCT LEAST(id, COALESCE(paired_position_id, id)))`.

## 2. Why this is correct + inert

- **Inert today:** with zero paired rows, `COALESCE(paired_position_id, id) = id`
  and `LEAST(id, id) = id`, so the expression reduces to `COUNT(DISTINCT id)` =
  `COUNT(*)` (id is PK) — byte-identical to the previous count. Behaviour only
  changes once complete sets exist, which requires Lane 2C-2 + the flag ON.
- **Robust grouping:** `LEAST(id, COALESCE(paired, id))` gives both legs of a set
  the same group key (their shared minimum) → counted once; a directional row
  keys to itself → once; a lone open leg whose sibling already closed still keys
  to a value → once (no under-count in that transient state).
- **Step 8 (correlated exposure) deliberately UNCHANGED:** each leg's `size_usdc`
  is that leg's own cost, so `SUM(size_usdc)` over a set already equals the true
  combined set cost (NOT 2× a notional) — no double-count to fix. A complete set
  is hedged (YES/NO anti-correlated, settles to a known $1/share), so counting it
  at full combined cost against the exposure cap is *conservative* (stricter than
  its real risk) — the safe direction. Crediting the hedge would only loosen the
  cap, so it is intentionally not done.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/config.py` (COMPLETE_SET_ARB_ENABLED flag)
- `projects/polymarket/crusaderbot/domain/risk/gate.py` (`_open_position_count` re-scope)
- `projects/polymarket/crusaderbot/tests/test_complete_set_gate_rescope.py` (new)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` (NEXT PRIORITY → 2C-2)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` (append)

## 4. What is working

- Flag defaults OFF (test). `_open_position_count` issues the set-aware query and
  returns the count (test). 24 tests pass incl. `test_concurrency_policy` (step-7
  cap behaviour) + `test_config_defaults` (no regression). ruff + py_compile clean.

## 5. Known issues / scope boundaries

- **No scan/booking wiring yet** — `COMPLETE_SET_ARB_ENABLED` has no reader until
  Lane 2C-2; the gate re-scope is inert until paired rows exist.
- **GateContext.complete_set flag deferred to 2C-2** (where the scan gates a set
  once on combined cost and skips side-specific checks) — added there with its
  consumer to avoid dead code here.
- Migration 078 must be applied to Supabase before 2C-2 books a set in PAPER.

## 6. What is next

- **Lane 2C-2 (MAJOR, PAPER):** dedicated complete-set scan branch (fetch both
  books → `fillable_complete_set` → gate once with a `GateContext.complete_set`
  flag on combined cost → `book_complete_set_paper`), behind
  `COMPLETE_SET_ARB_ENABLED`; live-quote logging; exit-watcher paired-skip
  (no mid-trade TP/SL for paired positions). Apply mig 078 to Supabase with it.
- **Lane 3 (MAJOR, owner-gated + SENTINEL):** LIVE two-leg FOK + naked-leg
  fallback + idempotent recovery.

---

- **Validation Tier:** MAJOR
- **Claim Level:** FOUNDATION
- **Validation Target:** set-aware concurrency count + default-OFF kill switch, in isolation
- **Not in Scope:** scan branch, set gating call, exit handling, LIVE — Lane 2C-2 / Lane 3
- **Suggested Next Step:** WARP🔹CMD/SENTINEL review; then Lane 2C-2 (scan wiring).
