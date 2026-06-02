# Complete-Set Arbitrage — Lane 1 (detection core)

**Branch:** `WARP/ROOT/complete-set-arb`
**Role:** WARP•R00T (owner-directed: "full two-leg execution")
**Validation Tier:** MAJOR (trading-core foundation; new strategy primitive)
**Claim Level:** FOUNDATION (pure detection core, not wired into runtime)

> Owner chose the full two-leg execution build (over the observer-first
> recommendation). Because this is the highest-complexity, most execution-risky
> lane in the system and production is pre-LIVE, it is built in safe phases. **This
> PR is Lane 1 only: the detection + sizing core, shipped UNWIRED (zero runtime
> risk) so the level-walking math is proven before any execution/DB/gate change.**

---

## 1. What was built

`domain/strategy/complete_set_arb.py` — a pure, synchronous, IO-free module:

- `CompleteSetQuote` dataclass — a fillable opportunity (shares, per-leg cost,
  avg pair cost, gross + net margin).
- `fillable_complete_set(yes_book, no_book, *, min_pair_margin, min_shares,
  max_shares, ...)` — walks both CLOB books cheapest-first and sizes the **largest
  profitable** complete-set buy. The marginal cost of the i-th pair
  (`yes_ask_level + no_ask_level`) is non-decreasing as depth is consumed, so
  profitable pairs form a prefix: include each matched chunk while
  `1.0 - marginal_cost >= min_pair_margin`, stop at the first that isn't. Bounds to
  the thinner leg, honours a `max_shares` cap, rejects sub-`min_shares` dust, and
  never reports a non-profitable quote.
- `tests/test_complete_set_arb.py` — 13 hermetic tests: empty/None books, single-
  level profit, unprofitable rejection, marginal crossover, Polymarket
  descending-ask ordering, string prices, degenerate-level skipping (price≤0 / ≥1 /
  size≤0), max_shares partial fill, min_shares floor, unequal-leg-depth bounding,
  non-positive-margin guard, multi-level accumulation.

The core models the real edge constraint: it measures **fillable** size from book
depth, not the top-of-quote — because the arb is bounded by the thin depth at
sub-$1.00 prices.

## 2. Current system architecture (this lane)

Pure function island. No imports of DB, execution, risk, or registry. Not added to
`bootstrap_default_strategies` and not a `BaseStrategy` subclass (a complete set has
no single `side`, so it does not fit `SignalCandidate` whose `VALID_SIDES =
("YES","NO")`). Nothing in the running system calls it yet → it cannot affect any
trade.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/domain/strategy/complete_set_arb.py` (new)
- `projects/polymarket/crusaderbot/tests/test_complete_set_arb.py` (new)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` (NEXT PRIORITY + epic plan)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` (append)

## 4. What is working

Detection + sizing math, fully unit-tested (13/13 pass, ruff clean). Given any pair
of order books it returns the correct fillable shares, per-leg cost, and net margin,
or `None` when no profitable/large-enough set exists.

## 5. Known issues / scope boundaries

- **Unwired by design.** No scan loop calls it; no orders; no positions; no gate
  change. Wiring is Lane 2.
- **Fee/slippage** is folded into the caller-supplied `min_pair_margin` floor; this
  lane does not model the exact Polymarket fee schedule (Lane 2 will pass a concrete
  buffer).
- **Edge is rare + UNMEASURED.** MMs normally quote YES+NO > $1.00 (the vig), so
  fillable sub-$1.00 sets are fleeting and thin. Frequency/profitability is not yet
  measured (no backtest — WARP-51 F-1). Lane 2 should log live quotes before any
  LIVE capital.

## 6. What is next (the epic — remaining lanes)

- **Lane 2 (MAJOR, PAPER):** representation for a SET intent (extend the side model
  or a parallel pair type) + PAPER two-leg execution booking a linked pair +
  `positions.paired_position_id` migration + risk-gate step 7/8 re-scope (count a
  set as 1 unit, exposure = set cost not 2×size) + scan-loop + registry + preset +
  a default-OFF feature flag. Exit = hold to resolution (reuse the redeem path).
- **Lane 3 (MAJOR, owner-gated + SENTINEL):** LIVE two-leg execution — FOK on both
  legs + naked-leg fallback/cleanup + idempotent partial-fill recovery. The
  dangerous part; gated behind the activation guards + its own flag. Also depends on
  the tracked pre-LIVE `live.py` `strategy_metadata` follow-up.

Reusable plumbing confirmed (feasibility scan): single-leg order submit (GTC+FOK),
dual-book fetch + depth, CTF redeem (settles both index sets), 13/15 gate steps.
New build: pair position model, two-leg execution + leg-risk handling, gate 7/8
re-scope.

---

- **Validation Tier:** MAJOR
- **Claim Level:** FOUNDATION
- **Validation Target:** the fillable-set detection/sizing math in isolation
- **Not in Scope:** order placement, position model, risk-gate changes, CTF
  split/merge, registry/preset wiring, LIVE execution — all Lane 2/3
- **Suggested Next Step:** WARP•SENTINEL review of the detection core, then scope
  Lane 2 (PAPER two-leg + pair model + gate re-scope) as the next branch.
