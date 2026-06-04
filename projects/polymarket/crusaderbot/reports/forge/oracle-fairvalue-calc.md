# Forge Report — oracle-fairvalue-calc (WARP-63, Chunk 2/4)

Role: WARP•R00T (build lane)
Branch: WARP/ROOT/oracle-fairvalue-calc
Parent: WARP-61 — Chainlink BTC/USD oracle layer for late_entry_v3
Date: 2026-06-04 09:22 Asia/Jakarta

## 1. What was built

A pure, I/O-free fair-value / edge calculator — the math core of the candle
edge engine described in WARP-61 — now with PER-ASSET sigma (BTC/ETH/SOL). No
network, no DB, no strategy import, so it is fully unit-testable in isolation and
can land in parallel with Chunk 1 (oracle client). Public pure functions:

- `compute_fair_value(delta, time_left, sigma) -> float` — P(candle closes Up)
  = `Phi(delta / (sigma * sqrt(time_left)))`, a zero-drift Gaussian close model.
  Takes a scalar `sigma` so the math stays asset-agnostic.
- `compute_edge(fair_up, ask_up, ask_down) -> EdgeResult` —
  `edge_up = fair_up - ask_up`, `edge_down = (1 - fair_up) - ask_down`.
- `normal_cdf(z)` — standard normal CDF via `math.erf` (stdlib only; saturates
  cleanly at +/-1, no scipy/numpy, no overflow).
- `compute_delta(oracle_now, price_to_beat)` — signed candle return helper
  (`oracle_now` = the asset's current Chainlink reading; source-agnostic).
- `sigma_for_asset(asset, sigma_map=None) -> float` — pure per-asset sigma
  resolver (case-insensitive; unknown / non-finite raises `ValueError` — no
  silent default to a wrong-vol sigma). Defaults to `DEFAULT_SIGMA_PER_SQRT_SEC`
  when no map is supplied.
- `annual_vol_to_sigma(annual_vol)` — documents/calibrates the sigma basis.

**Per-asset sigma (correctness, not cosmetics):** realized vol differs
materially across these markets — SOL > ETH > BTC — so a single shared sigma
misprices fair value on the higher-vol assets. Sigma is therefore a
`{btc, eth, sol}` map. Each default = `annual_vol / sqrt(31_557_600)`:

| Asset | sigma/sqrt-sec | ~Annualized | Basis |
|---|---|---|---|
| BTC | `0.00010` | ~56% | `0.00010 * sqrt(31_557_600) ~= 0.562` |
| ETH | `0.00013` | ~73% | ETH realized vol historically above BTC |
| SOL | `0.00020` | ~112% | SOL the most volatile of the three |

Configured via Settings (`ORACLE_BTC/ETH/SOL_SIGMA_PER_SQRT_SEC`, each
env-overridable) exposed as the `Settings.oracle_sigma_per_sqrt_sec` map
property. The calculator stays pure — the strategy layer (Chunk 3) passes this
map into `sigma_for_asset`; the calculator never reads Settings itself. A larger
sigma pulls `fair_up` toward 0.5 (less confident); smaller sharpens convergence.

## 2. Current system architecture (relevant slice)

New package `domain/strategy/oracle/` holds the candle edge engine. This chunk
adds only the pure math leaf:

```
domain/strategy/oracle/
  __init__.py        # re-exports the pure API (no network/DB pulled in)
  fair_value.py      # this chunk — pure functions, stdlib math only
  (chainlink client) # Chunk 1 — separate
  (strategy wiring)  # Chunk 3 — separate, into late_entry_v3
```

Data flow once fully wired (Chunks 1+3 land it; not in this chunk):

```
Chainlink BTC/USD --> price_to_beat + chainlink_now --> compute_delta
        |                                                     |
        +--> time_left (resolution_ts - now)                  v
        +--> sigma (Settings)  ----------------------> compute_fair_value
                                                              |
                  best_ask_up / best_ask_down --> compute_edge (edge_up/down)
                                                              |
                                          RISK gate --> EXECUTION (unchanged)
```

`fair_value.py` imports only `math` and `typing` — it does not import any
strategy, integration, or DB module, enforcing the "pure logic" boundary.

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/domain/strategy/oracle/__init__.py`
- `projects/polymarket/crusaderbot/domain/strategy/oracle/fair_value.py`
- `projects/polymarket/crusaderbot/tests/test_oracle_fair_value.py`

Modified:
- `projects/polymarket/crusaderbot/config.py`
  (per-asset `ORACLE_BTC/ETH/SOL_SIGMA_PER_SQRT_SEC` floats, each env-overridable,
  plus the `oracle_sigma_per_sqrt_sec` map property)

## 4. What is working

- 32/32 unit tests pass; `ruff check` clean; `py_compile` clean on all
  touched files.
- Per-asset sigma proven: the SAME `delta=0.0015`, `time_left=120s` yields
  materially different `fair_up` per asset — BTC `0.9145` > ETH `0.8539` >
  SOL `0.7532` (higher vol => nearer 0.5). Confirms per-asset wiring is real,
  not a shared scalar. `sigma_for_asset` is case-insensitive, honours a
  caller-supplied map, and raises on unknown / non-finite calibration.
- Done-criteria edge cases proven:
  - `time_left -> 0` (and `<= 0`): `fair_up -> 1.0` for Up deviation, `0.0` for
    Down; the zero-variance / past-resolution limit is exact at the boundary.
  - denominator underflow (`sigma * sqrt(time_left)` rounds to `0.0` with both
    tiny-but-positive): falls back to the same zero-variance bound, never raises
    `ZeroDivisionError`.
  - `delta = 0`: `fair_up = 0.5` exactly, independent of time / vol.
  - negative delta: `fair_up < 0.5`; positive delta: `> 0.5`; monotonic in delta.
  - missing best-ask falls back safely on the `0.01` CLOB tick (`CLOB_MIN_TICK`);
    non-finite / non-positive asks floored to the tick; asks > 1.0 clamped to 1.0.
- `fair_up` always within `[0, 1]`; non-finite (NaN/inf) inputs raise
  `ValueError` (no silent failure).
- No network, no DB, no strategy import (verified by import surface: `math`,
  `typing` only).

## 5. Known issues

- None functional. By design this chunk has no runtime wiring — the calculator
  is inert until Chunk 1 (oracle client) feeds it real Chainlink readings and
  Chunk 3 wires it into `late_entry_v3` gating (resolving sigma per the market's
  asset via `sigma_for_asset(asset, settings.oracle_sigma_per_sqrt_sec)`). The
  per-asset sigma defaults are documented realized-vol estimates, not yet fitted
  to live BTC/ETH/SOL vol (operator may tune each
  `ORACLE_{BTC,ETH,SOL}_SIGMA_PER_SQRT_SEC` once the oracle streams are live).

## 6. What is next

- Chunk 1: Chainlink BTC/USD data-streams client (`price_to_beat` capture).
- Chunk 3 (WARP-64, blocked on this): wire oracle + `compute_edge` gate into the
  `late_entry_v3` presets (Distance / Min Edge / Trend), RISK gate before
  EXECUTION preserved. WARP-64 is unblocked by this chunk.

---

Validation Tier   : STANDARD (pure logic, no execution / risk / capital path)
Claim Level       : FOUNDATION (pure calculator; runtime authority not claimed)
Validation Target : compute_fair_value / compute_edge / normal_cdf / compute_delta
                    / sigma_for_asset / annual_vol_to_sigma math correctness +
                    documented edge cases + per-asset sigma (SOL!=ETH!=BTC) materiality
Not in Scope      : Chainlink oracle client (Chunk 1), late_entry_v3 strategy
                    wiring (Chunk 3 / WARP-64), live trading, risk-gate changes
Suggested Next    : WARP🔹CMD review (STANDARD) -> proceed to Chunk 1 / unblock WARP-64
