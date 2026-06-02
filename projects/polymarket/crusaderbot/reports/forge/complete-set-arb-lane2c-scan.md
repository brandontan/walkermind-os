# Complete-Set Arbitrage — Lane 2C-2b (scan + PAPER booking activation)

**Branch:** `WARP/ROOT/complete-set-arb-lane2c-scan`
**Role:** WARP•R00T (owner-directed: "full two-leg execution")
**Validation Tier:** MAJOR (runtime activation — risk gate + execution wiring)
**Claim Level:** NARROW INTEGRATION (PAPER scan→gate→book, behind a default-OFF flag)

> Lane 2C-2b is the FINAL PAPER piece of the complete-set arb epic. It joins the
> Lane-1 detector (`fillable_complete_set`) to the Lane-2B booker
> (`book_complete_set_paper`) through the risk gate, for enrolled users on candle
> presets — all behind `COMPLETE_SET_ARB_ENABLED` (default OFF). LIVE is the
> separate owner-gated Lane 3.

## 1. What was built

A complete-set arbitrage scan + PAPER booking path, dark by default:

- **`domain/risk/constants.py`** — `STRATEGY_AVAILABILITY` gains `complete_set_arb`
  (all profiles; the set is hedged/riskless, sizing still bounded by Kelly +
  max-position in gate step 13). Without this, gate step 4 rejects every set as
  `unknown_strategy`.
- **`domain/risk/gate.py`** — `GateContext.complete_set: bool = False` + a step-13
  hard-cap path. A set quote is a fixed YES+NO share count, so the gate must NOT
  Kelly-shrink the combined cost (that would desync the approved size from the
  legs the booker buys). When `complete_set` is set it passes the combined cost
  through unchanged and HARD-REJECTS (`complete_set_size_over_cap`) if it exceeds
  the per-position cap (the scan already sizes within it, so a reject is a real
  misconfiguration, not normal flow).
- **`services/signal_scan/complete_set_scan.py`** (new) —
  `scan_complete_set_for_user(row, markets, *, settings, book_fetcher,
  gate_evaluate, booker, balance_reader)`. Per candidate market: fetch both order
  books → `fillable_complete_set` (bounded by a capital-derived `max_shares`) →
  **log the live quote BEFORE any capital** → build a `GateContext`
  (`complete_set=True`, combined cost, `edge_bps=None`) → `gate.evaluate` (once,
  on the combined cost) → `book_complete_set_paper` (PAPER only). Dependencies are
  injected so the pipeline is hermetically unit-testable.
- **`services/signal_scan/signal_scan_job.py`** — wires the above into `run_once`
  as **Phase B3**, gated behind `COMPLETE_SET_ARB_ENABLED` and scoped to candle
  presets (reuses the crypto-window market fetch already done for those presets).
  Normalized market rows are reloaded via `_load_market` so the scan sees real
  token ids + liquidity. Fail-soft: any error is logged, never blocks the loop.

## 2. Safety posture (why this is safe to land dark)

- **Master flag** `COMPLETE_SET_ARB_ENABLED` (default OFF) gates the entire Phase
  B3 branch — nothing scans or books until the operator flips it.
- **Second floor**: `min_pair_margin` reuses `MIN_COMPLETE_SET_EDGE` (default
  0.0). `fillable_complete_set` returns `None` for a non-positive margin, so even
  with the master flag ON, nothing books until the operator also sets a positive
  edge floor — double-safe.
- **Sizing**: the quote is bounded up front by `max_shares` (Kelly *
  max_pos_pct * balance, in shares — each pair costs < $1 so the share cap keeps
  the combined cost below the USDC cap), and the gate re-checks it as a hard
  reject. No silent Kelly shrink that would desync from the booked legs.
- **PAPER only**: the booker is the paper primitive; an unexpected
  `chosen_mode != "paper"` is skipped, never executed. LIVE = Lane 3.
- **Exit protection already in place** (Lane 2C-2a, merged #1563): a booked set
  is held to resolution across `evaluate()` + both `run_once` expiry paths.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/domain/risk/constants.py` (STRATEGY_AVAILABILITY)
- `projects/polymarket/crusaderbot/domain/risk/gate.py` (GateContext.complete_set + step 13)
- `projects/polymarket/crusaderbot/services/signal_scan/complete_set_scan.py` (new)
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` (Phase B3 wiring)
- `projects/polymarket/crusaderbot/tests/test_complete_set_scan.py` (new — 13 tests)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`
- Supabase prod `ykyagjdeqcgcktnpdhes`: migration 078 ledger reconciled (see §5)

## 4. What is working

- 13 new tests in `test_complete_set_scan.py` pass:
  - 9 pipeline: happy-path (detect→log→gate→book), dormant-margin (no book fetch),
    no-fillable-arb (no book), gate-rejection-blocks-booking, live-decision-skipped,
    capital-too-small-early-return, missing-tokens-skipped, resolved-market-skipped,
    per-market-error-isolated.
  - 4 gate step-13 `complete_set`: size passes through unshrunk when within cap;
    rejects `complete_set_size_over_cap` when over.
- 200 related-area tests pass (complete_set arb/exec/gate-rescope/edge-gate,
  signal_scan_job, exit_watcher, concurrency). `ruff` + `py_compile` clean.

## 5. Known issues / scope boundaries

- **Migration 078 — schema was already applied; ledger reconciled.** On inspecting
  Supabase prod (`ykyagjdeqcgcktnpdhes`) the `positions.paired_position_id` column,
  its self-FK (`ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED`), and the partial
  index `idx_positions_paired` were already present (contradicting the earlier
  "not yet applied" note). `apply_migration` was run with the idempotent
  `IF NOT EXISTS` SQL — a no-op on the schema that recorded the missing ledger
  entry (version `20260602114243`). FK deferrable/set-null + index verified via
  `pg_constraint` / `pg_indexes`.
- **Candle-preset scoped**: Phase B3 only runs for candle presets because the
  crypto-window market fetch (the binary YES/NO markets where the MM-vig
  dislocation appears) is only done for those presets. Broadening the universe is
  a future lane if the logged quotes justify it.
- **Per-tick `_load_market` reads**: N normalized-row reloads per candle user per
  tick — zero cost while the flag is OFF (the default); cheap when ON (candle
  windows are small).
- **Edge is rare + UNMEASURED**: the live-quote log is the observability that must
  precede any decision to set a positive `MIN_COMPLETE_SET_EDGE`.

## 6. What is next

- **Operator (when ready to observe)**: set `COMPLETE_SET_ARB_ENABLED=true` and
  watch `complete_set_quote` logs; keep `MIN_COMPLETE_SET_EDGE=0` until quotes are
  seen, then raise it to begin PAPER booking.
- **Lane 3 (MAJOR, owner-gated + SENTINEL)**: LIVE two-leg execution (FOK +
  naked-leg fallback + idempotent recovery), depends on the tracked pre-LIVE
  `execution/live.py` `strategy_metadata` follow-up.

---

- **Validation Tier:** MAJOR
- **Claim Level:** NARROW INTEGRATION
- **Validation Target:** complete-set scan → gate → PAPER book wiring, behind COMPLETE_SET_ARB_ENABLED
- **Not in Scope:** LIVE execution, broadening beyond candle presets — Lane 3 / future
- **Suggested Next Step:** WARP•SENTINEL MAJOR audit (gate flag + scan isolation), then owner merge.
