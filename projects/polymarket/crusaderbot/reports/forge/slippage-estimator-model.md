# WARP-83 Sub-Lane A — Slippage Estimator Model

Validation Tier: MAJOR
Claim Level: FOUNDATION
Validation Target: the pure pre-trade slippage estimator `domain/research/slippage_estimator.py` (functional correctness, edge/guard behavior, monotonicity) — NOT any runtime wiring, NOT a parameter empirical fit.
Not in Scope: ev_comparator / scorer_trainer / orchestrator (untouched); `domain/execution/slippage.py` (untouched); §1.7 cutover verdict logic (unchanged); new orderbook capture (none — respects WARP-82); new runtime deps (none); caller integration / sizing pipeline wiring (no caller yet).
Suggested Next Step: WARP•SENTINEL validation of the estimator's correctness + guard behavior, then a separate lane to wire it to a caller (sizing / EV) and empirically fit `impact_coeff` from settled `factor_vectors` realized slippage.

---

## 1. What was built

A pure, deterministic pre-trade slippage estimator that maps already-available
`factor_vectors` fields to an expected slippage in basis points.

Public surface (`domain/research/slippage_estimator.py`):

- `estimate_slippage_bps(*, stake_usdc, orderbook_depth_usdc, spread, entry_price, current_price=None, impact_coeff=..., move_coeff=..., spread_cross_fraction=...) -> SlippageEstimate`
- `SlippageEstimate` (frozen dataclass): `total_bps`, `spread_cost_bps`, `impact_bps`, `adverse_move_bps`, `participation_ratio`, `illiquid_book`.
- Tunable module constants: `IMPACT_COEFF_DEFAULT`, `MOVE_COEFF_DEFAULT`, `SPREAD_CROSS_FRACTION_DEFAULT`, `ILLIQUID_PARTICIPATION_CEILING`, `MIN_USABLE_DEPTH_USDC`.

The estimator does NO network, NO DB, NO async, NO clock reads — the caller
supplies all factor inputs. Only stdlib `math` + the project's existing
`structlog` are used (no new runtime deps).

### Model equation

```
slippage_bps = spread_cost_bps
             + impact_coeff * sqrt(stake_usdc / orderbook_depth_usdc) * 1e4
             + move_coeff   * abs_price_move_bps

where
  spread_cost_bps   = max(0, spread - 1.0) * spread_cross_fraction * 1e4
  abs_price_move_bps= abs(current_price - entry_price) / entry_price * 1e4
```

Three additive components:

1. **Spread cost** — On Polymarket the `spread` factor is the complete-set cost
   `yes_ask + no_ask` (~1.0 for a liquid binary market; observed mean 1.0119,
   range 0.69–1.86 over 1822 rows). Its excess over the 1.0 fair complete-set
   value is the round-trip spread; a single-leg taker crosses
   `spread_cross_fraction` (default 0.5) of it. Negative excess is floored at 0.

2. **Market impact** — a square-root law in the participation ratio
   `stake_usdc / orderbook_depth_usdc`. Square-root (concave) is chosen over
   linear so a small stake against a deep book incurs near-zero impact while a
   large stake against a thin book is penalized super-linearly in the ratio.

3. **Adverse price move** — when the live `current_price` has already drifted
   from the intended `entry_price`, that realized move is an additional
   execution cost, scaled by `move_coeff` (default 1.0). Skipped when
   `current_price is None` or `entry_price <= 0`.

### Parameter rationale + citation

- **Square-root functional form** — the empirically robust market-impact law
  across asset classes: impact grows ~ `sqrt(executed volume / available
  liquidity)`. Grounded in Bouchaud et al.'s locally-linear-order-book (LLOB)
  / "markets never forget" square-root-impact line of work, and corroborated
  for prediction markets specifically by "The Anatomy of a Decentralized
  Prediction Market: Microstructure Evidence from the Polymarket Order Book"
  (arXiv:2604.24366), which documents depth concentration and concave,
  depth-driven impact in Polymarket binary markets. Almgren et al. (2005)
  likewise find concave (≈3/5–square-root) impact in trade size.
- **`IMPACT_COEFF_DEFAULT = 0.02`** — conservative baseline: a stake equal to
  the full book (ratio 1.0) yields ~200 bps impact before sqrt damping; pending
  an empirical fit against settled realized slippage.
- **`SPREAD_CROSS_FRACTION_DEFAULT = 0.5`** — a single taker leg crosses ~half
  the round-trip spread.
- **`MIN_USABLE_DEPTH_USDC = 1.0` / `ILLIQUID_PARTICIPATION_CEILING = 4.0`** —
  div-by-zero guard: a non-positive / near-zero / non-finite book is treated as
  maximally illiquid, ratio clamped to the ceiling and the condition flagged +
  WARNING-logged (never silent). The ceiling also caps extreme stake/depth so
  the impact term stays finite and bounded.

### Field dependencies (all on the existing `factor_vectors` surface)

- `orderbook_depth_usdc` — required (impact denominator).
- `spread` — required (complete-set cost → spread component).
- `entry_price` — required (adverse-move denominator).
- `current_price` — optional (adverse-move numerator; positions-table live mark).
- `stake_usdc` — caller-derived order notional (e.g. from sizing); not a factor
  field but the impact numerator.
- `liquidity_usdc`, `complete_set_edge` — present on the surface and verified
  available; not consumed by the current functional form (reserved for a future
  fit), so no fabricated dependency.

## 2. Current system architecture

```
factor_vectors fields (caller supplies)
  orderbook_depth_usdc, spread, entry_price, current_price, + stake_usdc
        |
        v
domain/research/slippage_estimator.estimate_slippage_bps  (PURE)
        |  _participation_ratio (div-by-zero guard + clamp + WARNING)
        |  _spread_cost_bps (complete-set excess, floored)
        |  sqrt impact + adverse-move
        v
SlippageEstimate(total_bps, spread_cost_bps, impact_bps, adverse_move_bps,
                 participation_ratio, illiquid_book)
        |
        v
(future) caller: pre-trade EV / sizing research consumes total_bps
```

Concern separation:

- `domain/execution/slippage.py` — execution-time accept/reject guardrails
  (market-impact ratio gate `size/liquidity > MAX_MARKET_IMPACT_PCT`; live
  price-deviation gate). Answers "is this order allowed?". UNTOUCHED.
- `domain/research/slippage_estimator.py` (this lane) — pre-trade *estimation*
  of slippage magnitude in bps. Answers "how much will it cost?". The two
  compose: the guard keeps its ratio gate; research consumes the bps estimate.

## 3. Files created / modified (full repo-root paths)

Created:

- `projects/polymarket/crusaderbot/domain/research/slippage_estimator.py`
- `projects/polymarket/crusaderbot/tests/test_slippage_estimator.py`
- `projects/polymarket/crusaderbot/reports/forge/slippage-estimator-model.md`

Modified (state sync):

- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- 15/15 tests pass:
  `python -m pytest projects/polymarket/crusaderbot/tests/test_slippage_estimator.py -q`
  → `15 passed`.
- `ruff check` clean on both new files.
- Coverage: baseline shape + component decomposition; tight-spread (zero spread
  cost at fair value); sub-fair spread floored; thin-book-large-stake high
  impact; participation clamp on extreme stake; zero / near-zero / negative
  depth → `illiquid_book=True` + finite output (no div-by-zero, no silent
  failure); non-finite inputs coerced (no NaN/inf propagation); adverse move
  adds cost / `None` / zero-entry skip; monotonicity in stake-over-depth, in
  spread, and inverse-monotonic in depth.
- Field availability verified read-only via Supabase (project
  ykyagjdeqcgcktnpdhes): `factor_vectors` has 1822 rows; `orderbook_depth_usdc`,
  `spread`, `entry_price`, `liquidity_usdc`, `complete_set_edge` all 100%
  non-null; `orderbook_depth_usdc > 0` on all rows. No STOP condition — data is
  sufficient to support the model.

## 5. Known issues

- `impact_coeff` (and `move_coeff`) are reasoned baselines, NOT empirically
  fitted to realized slippage. A follow-up lane should regress realized entry
  slippage on `sqrt(stake/depth)` from settled `factor_vectors` to calibrate.
- `stake_usdc` is not a `factor_vectors` field; the caller must supply the
  intended order notional from the sizing layer.
- The model attributes the full pre-existing `abs_price_move` to slippage when
  `current_price` is supplied; if the caller already accounts for repricing
  separately it should pass `move_coeff=0.0` or omit `current_price`.
- No caller is wired yet (FOUNDATION) — the estimator is a pure function only.

## 6. What is next

- WARP•SENTINEL validation (MAJOR) of correctness + guard behavior.
- Separate lane: empirical calibration of `impact_coeff` from settled rows.
- Separate lane: wire `total_bps` into pre-trade EV / sizing research (caller
  integration), keeping the execution-time guard in `domain/execution/slippage.py`.

---

File placement decision: the task spec referenced `late_entry/slippage_estimator.py`,
but there is no `late_entry/` directory. Placed at
`projects/polymarket/crusaderbot/domain/research/slippage_estimator.py` (the
research / modeling module), consistent with the existing research plane
(`late_entry_oos_evaluator.py`, `factor_dataset.py`, etc.). This is a distinct
concern from `domain/execution/slippage.py` (execution-time accept/reject guard),
which was read first to avoid duplication and is referenced but not modified.
