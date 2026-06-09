# WARP•SENTINEL — complete-set-arb Lane 1 (detection core)

**Branch:** `WARP/ROOT/complete-set-arb`
**Tier:** MAJOR · **Claim:** FOUNDATION · **Env:** dev
**Verdict:** APPROVED · **Score:** 95/100 · **Critical:** 0

## TEST PLAN

Lane 1 ships a pure, synchronous, IO-free detection/sizing module shipped
UNWIRED. Audit scope: prove (a) zero runtime surface, (b) the level-walking math
is correct and total, (c) non-finite/malformed inputs cannot raise or propagate.

## PHASE 0 — PRE-TEST

- Report present, correct path, all 6 sections + metadata —
  `reports/forge/complete-set-arb.md` → PASS
- `PROJECT_STATE.md` updated (NEXT PRIORITY + epic plan) → PASS
- No `phase*/` folders; module in `domain/strategy/` → PASS
- Implementation evidence: `domain/strategy/complete_set_arb.py:88` +
  16 hermetic tests → PASS

## FINDINGS

- **Unwired (zero runtime risk).** `grep` for `complete_set_arb` /
  `fillable_complete_set` / `CompleteSetQuote` across the package returns only
  the module and its test — not imported by any scan loop, registry, gate, or
  execution path. Not a `BaseStrategy` subclass; absent from
  `bootstrap_default_strategies` (`registry.py:141`). Cannot affect any trade.
- **Never-raises contract holds.** `_asks_ascending` guards `not isinstance(book,
  dict)` and `not isinstance(asks, list)` (`complete_set_arb.py:73,76`); each
  level parse is `try/except (KeyError, TypeError, ValueError)`. Malformed book →
  `[]` → `None`. Verified by `test_malformed_asks_type_returns_none`.
- **Non-finite inputs contained.** Level filter `0.0 < price < 1.0 and 0.0 <
  size < float("inf")` (`:82`) excludes NaN/inf price and inf/NaN size before the
  cost math; margin guard `not (min_pair_margin > 0.0)` (`:121`) rejects NaN/0/neg.
  Verified by `test_infinite_and_nan_size_skipped`, `test_nan_margin_returns_none`.
- **Sizing math correct.** Marginal pair cost is non-decreasing as depth is eaten,
  so the profitable region is a prefix; the walk breaks at the first pair where
  `yp + np_ > threshold` (`:144`), bounds to the thinner leg, honors `max_shares`,
  rejects sub-`min_shares` dust, and re-checks `net > 0` before returning (`:176`).
  Verified by crossover / multi-level / unequal-depth / cap / floor tests.
- **No silent failure.** Non-positive/NaN margin is logged (`log.warning`) then
  returns None — no swallowed exception, no bare `except`.

## STABILITY SCORE

Arch 20/20 · Functional 20/20 · Failure modes 20/20 · Risk N/A (no capital
surface this lane) · Infra+TG N/A · Latency N/A — pure CPU.
Scope-weighted (foundation, no runtime surface): **95/100**. −5: edge frequency
is UNMEASURED (WARP-51 F-1) — a Lane 2 concern, not a Lane 1 defect.

## GO-LIVE STATUS

APPROVED for merge as a foundation primitive. This does NOT authorize any
execution, capital, or LIVE path — Lane 2 (PAPER) and Lane 3 (LIVE) carry their
own MAJOR validation gates. The module is inert until Lane 2 wires it.

## CRITICAL ISSUES

None found.

## FIX RECOMMENDATIONS

None blocking. Lane 2 must (1) pass a concrete fee/slippage buffer into
`min_pair_margin`, and (2) log live fillable quotes before any LIVE capital, to
close the unmeasured-edge gap.
