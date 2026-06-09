# WARP•FORGE — late-entry-oos-validation (WARP-58, lane WARP-54)

Role: WARP•FORGE
Validation Tier: **STANDARD**
Claim Level: **NARROW INTEGRATION**
Validation Target: OOS edge of `late_entry_v3` across the 3 canonical presets
(`close_sweep` / `safe_close` / `flip_hunter`), net of fees + slippage.
Not in Scope: wiring `edge_bps` into the risk gate (WARP-55); any entry-logic or
risk-constant change; live execution; enabling snapshot capture (operator action).
Suggested Next Step: operator enables `SCAN_SNAPSHOT_ENABLED` (#1579) + applies
mig 080 → let `market_snapshots` accrue ≥ `MIN_OOS_TRADES` → re-run
`domain/research/late_entry_oos.py` → feed the realized `edge_bps` into WARP-55.

---

## Headline finding

**OOS edge is currently UNPROVEN for all three presets — it cannot be measured
today because the empirical substrate is empty.** This is the "or prove no edge
exists" branch of the task: no positive `edge_bps` can be defended, and none was
fabricated. The measurement harness runs, is tested, and returns 0 trades because
`market_snapshots` holds no data (snapshot capture has never been enabled with
retained history, and the dev environment has no database). The empirical input
WARP-55 depends on is therefore: **treat `late_entry_v3` as edge-unproven
(edge_bps = 0 / UNPROVEN) until snapshot data accrues.**

### OOS results table (per preset)

| preset        | n_trades | hit-rate | gross EV/trade | net EV/trade | suggested edge_bps | status            |
|---------------|---------:|---------:|---------------:|-------------:|-------------------:|-------------------|
| close_sweep   | 0        | N/A      | N/A            | N/A          | **UNPROVEN**       | UNPROVEN_NO_DATA  |
| safe_close    | 0        | N/A      | N/A            | N/A          | **UNPROVEN**       | UNPROVEN_NO_DATA  |
| flip_hunter   | 0        | N/A      | N/A            | N/A          | **UNPROVEN**       | UNPROVEN_NO_DATA  |

Captured from a real run of `python -m projects.polymarket.crusaderbot.domain.research.late_entry_oos`
in this environment (snapshot read fail-soft → `[]` → every preset UNPROVEN_NO_DATA).

### Evidence (file:line)

- `projects/polymarket/crusaderbot/config.py:156` — `SCAN_SNAPSHOT_ENABLED: bool = False`
  (capture default OFF; the substrate accrues nothing until an operator flips it).
- `projects/polymarket/crusaderbot/domain/research/replay.py:181` — `replay()` is
  **inert on an empty table → returns `{}`**; fail-soft on every DB touch.
- `projects/polymarket/crusaderbot/domain/research/snapshots.py:7` — capture is
  gated by `SCAN_SNAPSHOT_ENABLED` at the call site; no rows exist without it.
- Dev env: no `DATABASE_URL` set → `market_snapshots` is unreachable/empty (probed;
  `replay`/harness fail-soft to `[]`).
- No historical data files (`.csv`/`.parquet`/`.jsonl`) anywhere in the repo.
- `state/PROJECT_STATE.md` KNOWN ISSUES + line ~185 (F-1): "no backtest/validation
  framework… every candle param tuned by imitating reference bot Kreo, zero OOS
  support" — this lane confirms F-1 empirically: the harness exists, the data does not.

---

## 1. What was built

A runnable, tested **OOS edge-measurement harness** that wires `late_entry_v3`'s
three presets through the **existing** walk-forward replay engine and nets the
transaction costs the base engine does not model — ready to emit real per-preset
`edge_bps` the moment `market_snapshots` accrues data, and which correctly reports
UNPROVEN today.

`domain/research/late_entry_oos.py`:
- `CostModel` — round-trip taker fees + slippage as a fraction of the side's entry
  notional (the same denominator `replay.trade_return` uses), subtracted per trade
  so a marginal gross winner can flip to a net loser and the hit-rate reflects costs.
- `build_decider(preset)` — a `decide(row) -> (module, side) | None` for the existing
  `replay()`; a faithful mirror of `late_entry_v3` entry gating against a snapshot
  row, importing the **real** per-preset params (`_CANDLE_PRESET_STATIC`), with a
  documented in-module fallback mirror so dep-light research envs still use correct
  thresholds.
- `run_oos(...)` — per preset, builds trades over the snapshot substrate (reusing
  `replay`'s pure units `trade_return`/`compute_metrics`/`has_leakage`), nets costs,
  and returns an `OOSResult` (`MEASURED` / `UNPROVEN_THIN` / `UNPROVEN_NO_DATA`).
  A preset is only credited an `edge_bps` once it clears `MIN_OOS_TRADES`.
- `format_table` + `__main__` — prints the per-preset table.

`tests/test_late_entry_oos.py` (9 tests, all pass): cost-model math, per-trade
netting (incl. a winner→loser flip), decider in/out-of-window + price-band gating,
flip_hunter underdog side selection, empty-substrate inertness (all UNPROVEN_NO_DATA),
and thin-sample (`UNPROVEN_THIN`, no edge credited).

## 2. Current system architecture

No runtime/trading change. The harness is a pure read-side research module over
`market_snapshots` plus preset-specific decision callables — the same design
contract `replay.py` uses to avoid sim/live drift (caller supplies the decision
logic; the engine scores it OOS). It is invoked on demand; nothing calls it
automatically. The strategy module (`late_entry_v3.py`), the risk gate, Kelly,
and `ENABLE_LIVE_TRADING` are untouched.

Cost model (round-trip, taker): entry crosses the spread to take the favored/
underdog side (~half-spread), exit crosses to settle/flip (~half-spread), plus
`slip_ticks_per_side * tick_size` adverse fill per side and a `fee_bps` notional
fee. `fee_bps` defaults to 0 — no canonical fee constant exists in-repo, so it is
an explicit, overridable assumption rather than an invented number; `tick_size`
0.01 matches `domain/execution/slippage`.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/domain/research/late_entry_oos.py` — NEW (harness)
- `projects/polymarket/crusaderbot/tests/test_late_entry_oos.py` — NEW (9 tests)
- `projects/polymarket/crusaderbot/reports/forge/late-entry-oos-validation.md` — this report
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — Last Updated; COMPLETED
  + NEXT PRIORITY + KNOWN ISSUES bullets for this lane; **piggyback** no-side-pnl-frame
  status sync `(PR open)`/`PR open.` → `MERGED #1585` (3 occurrences, status token only)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — lane entry appended

## 4. What is working

- Harness runs end-to-end and is fail-soft: with no DB it reads `[]` and returns an
  UNPROVEN_NO_DATA row per preset (verified — see the table above).
- 9/9 tests pass; `ruff` clean on the new module + test.
- Per-preset deciders import the real gate params; the cost model nets per trade
  and is unit-pinned (incl. the cost-induced winner→loser flip).
- The measurement is reproducible: the instant `market_snapshots` has data, the
  same command emits MEASURED rows with realized `edge_bps`.

## 5. Known issues

- **OOS edge UNPROVEN — empty substrate (the headline).** Until `SCAN_SNAPSHOT_ENABLED`
  is enabled and `market_snapshots` accrues ≥ `MIN_OOS_TRADES`, every preset is
  UNPROVEN_NO_DATA. No `edge_bps` can be defended; do not credit `late_entry_v3`
  with positive edge in WARP-55.
- **Entry-snapshot fidelity (documented limitation).** The base `replay()` groups one
  entry (earliest retained snapshot) + one settlement (latest) per market; `late_entry_v3`
  enters in the final seconds. The decider therefore only admits a market when its
  earliest retained snapshot already sits inside the preset entry window — faithful
  but conservative (under-sampling). A final-window snapshot selector is a follow-up
  once data exists, and may itself be a WARP-55 prerequisite for a tight edge estimate.
- **Opposite-leg reconstruction.** Only one book is stored per snapshot; the opposite
  leg's ask is approximated (`no_ask ≈ 1 - yes_bid`). Documented in-module.
- **`fee_bps` assumption.** No repo fee constant exists; default 0 with explicit,
  overridable knobs. Net edge is dominated by the slippage term regardless.

## 6. What is next

1. **WARP🔹CMD review** of this STANDARD lane (no SENTINEL — STANDARD tier).
2. Operator: enable `SCAN_SNAPSHOT_ENABLED` (#1579) + apply mig 080; let
   `market_snapshots` accrue across real candle cycles.
3. Re-run `domain/research/late_entry_oos.py` → realized per-preset `edge_bps`
   (or a confirmed no-edge result if net EV ≤ 0).
4. **WARP-55** consumes the result for the edge-floor dispatch. Until then the floor
   must treat `late_entry_v3` as edge-unproven (0 / UNPROVEN), consistent with the
   KNOWN ISSUES entry that `edge_bps` is hardcoded `None` and gate step 12 is inert.

---

Done criteria coverage: report at correct path with all 6 sections + metadata ✓;
OOS table for all 3 presets (explicit UNPROVEN/no-edge finding) ✓; PROJECT_STATE
synced incl. no-side-pnl-frame `MERGED #1585` piggyback ✓; CHANGELOG appended ✓.
