# SMART STRIKE — durable factor dataset (WARP-72 Phase 2 prep)

**Role:** WARP•R00T (build, shadow-only)
**Linear:** WARP-72 (Phase 2 prerequisite — persist the labeled dataset before deriving weights)
**Branch:** WARP/ROOT/factor-dataset-persistence
**Predecessor:** WARP-72 Phase 1 (`smart-strike-factor-signals`) MERGED #1608 (squash 8277937).

**Validation Tier:** MAJOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** the durable `factor_vectors` sink — one-row-per-candle UPSERT recorder, the settlement backfill that resolves realized open→close from the oracle ring, the scheduler job, and the gating. Shadow/telemetry only.
**Not in Scope:** the Phase-2 scorer / weight derivation; any selection/router/risk-gate/sizing change; backfilling rows that predate the table; deriving weights from the dataset (deferred until a settled sample accrues).
**Suggested Next Step:** operator applies migration 081 + enables `ORACLE_ENABLED` in paper; let the dataset accrue settled `open_to_close` rows; then WARP-72 Phase 2 derives weights from those rows only.

---

## 1. What was built

A durable, queryable home for the Phase-1 factor vector so Phase 2 can derive weights from **real settled outcomes** instead of logs. Per the operator spec:

1. **Sink = Supabase table `factor_vectors`** (migration `081_factor_vectors.sql`), not just logs — durable, queryable, restart-safe, RLS deny-by-default (mirrors `market_snapshots`).
2. **A row for EVERY evaluated candle (traded or not)** — the recorder is called from `_evaluate_market` for all evaluated candles, the same decoupled point the factor vector emits, preserving the unbiased dataset (not only traded positions).
3. **Settlement backfill** — the row is written at the entry-decision point with the **provisional** outcome (`open→now`), then a scheduled job UPDATEs it with the realized **open→close** outcome at candle resolution, joined by `condition_id`, stamping `outcome_source` (`provisional` → `open_to_close`, or `unresolved` when the open tick has aged out of the oracle ring).
4. **GRAIN = one row per candle**, keyed by `condition_id` (each candle slot is a distinct market). The recorder UPSERTs latest-wins and is **write-throttled** per candle, so many scans collapse to one labeled example — never one row per scan tick (which would bloat + autocorrelate the dataset).
5. **Shadow/telemetry only** — no selection change, no scorer, fail-soft everywhere; gated by `FACTOR_DATASET_PERSIST_ENABLED` (default ON). Phase 2 will train on **settled `open_to_close` rows only**.

The state-sync housekeeping (Phase 1 → MERGED; this lane) is folded in.

---

## 2. Current system architecture

```
late_entry_v3._evaluate_market (per evaluated candle, traded or not)
   └─ _observe_factor_vector(...) -> FactorVector  (build + emit log)   [Phase 1]
        └─ _persist_factor_vector(fv)  (gated, fail-soft)               [NEW]
             └─ factor_dataset.record_factor_vector(fv)
                  └─ UPSERT factor_vectors  ON CONFLICT(condition_id)    one row/candle
                     DO UPDATE ... WHERE settled = FALSE   (latest-wins, throttled)

signal_scan_job._scan_late_entry_for_preset (router picks winner)       [Phase 1 dedup unchanged]
   └─ mark_router_selection(meta, rule)                                 [Phase 1, metadata]
   └─ _persist_factor_router_selection(condition_id, rule)              [NEW]
        └─ factor_dataset.mark_router_selection_row(...)  UPDATE ... WHERE settled = FALSE

scheduler (every FACTOR_SETTLEMENT_INTERVAL_SEC=60s, gated)             [NEW]
   └─ signal_scan_job.run_factor_settlement_backfill()
        └─ factor_dataset.backfill_factor_settlement(oracle.price_at)
             SELECT settled=FALSE AND candle_close_epoch<=now
             price_at(open), price_at(close) -> realized_candle_outcome
             UPDATE ... outcome_source='open_to_close', settled=TRUE
             (aged out of ring -> 'unresolved'; still in window -> retry next pass)
```

The capital path (selection → pre-gates → 13-step risk gate → execution) is unchanged. The only additions are fail-soft DB writes + one scheduled job, all behind `FACTOR_DATASET_PERSIST_ENABLED`.

---

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/migrations/081_factor_vectors.sql` — the table (PK `condition_id`, partial indexes for the backfill + Phase-2 slicing, RLS).
- `projects/polymarket/crusaderbot/domain/research/factor_dataset.py` — `record_factor_vector` (throttled UPSERT), `mark_router_selection_row`, `backfill_factor_settlement` + `_write_settled`.
- `projects/polymarket/crusaderbot/tests/test_warp72_factor_dataset.py` — 9 tests.

Modified:
- `projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py` — `_observe_factor_vector` now returns the `FactorVector`; `_evaluate_market` stamps `factor_*` metadata and `await _persist_factor_vector(fv)` (gated, fail-soft) for every evaluated candle.
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — `_persist_factor_router_selection` on the router winner; `run_factor_settlement_backfill` job wrapper (resolves via the oracle ring).
- `projects/polymarket/crusaderbot/scheduler.py` — registers `run_factor_settlement_backfill` (gated).
- `projects/polymarket/crusaderbot/config.py` — `FACTOR_DATASET_PERSIST_ENABLED` (default True), `FACTOR_SETTLEMENT_INTERVAL_SEC` (default 60).
- `state/PROJECT_STATE.md`, `state/WORKTODO.md`, `state/CHANGELOG.md` — sync (Phase 1 merged + this lane).

---

## 4. What is working

- 9/9 new dataset tests pass; touched suites green (190 incl. `late_entry_v3`, `oracle_edge_wiring`, `candle_auto_router`, `signal_scan_job`, `research_snapshots`). `ruff` clean.
- Recorder: INSERT/UPSERT column↔value alignment (34 cols), `ON CONFLICT(condition_id) ... WHERE settled = FALSE` (settled rows immutable), `selected_by_router` bool coercion.
- GRAIN throttle verified: repeated same-candle writes within the gap collapse to one DB write; distinct candles are not throttled; empty `condition_id` skipped; DB error is fail-soft (returns False).
- Router-selection UPDATE shape verified (`WHERE ... settled = FALSE`).
- Settlement: open→close resolves to `UP/DOWN` with `outcome_source='open_to_close'` + `settled=TRUE`; aged-out rows → `unresolved`; still-in-ring-window unresolved rows are left for the next pass (no premature settle).

### Evidence (hermetic, fake pool)

```
record_factor_vector: INSERT INTO factor_vectors (...34 cols...) ON CONFLICT (condition_id)
  DO UPDATE SET ... WHERE factor_vectors.settled = FALSE        args[0]=condition_id, len=34
throttle: write@1000 -> True ; write@1002 (<5s) -> False ; write@1010 -> True   (1 row, 2 writes)
settlement: rows[close<=now], price_at(open)=104000 price_at(close)=104600
  -> UPDATE ... realized_outcome='UP' open=104000 close=104600 outcome_source='open_to_close' settled=TRUE
aged-out: close 1800s+ ago, price_at=None -> outcome_source='unresolved' settled=TRUE
```

---

## 5. Known issues

- **Settled label needs the oracle.** With `ORACLE_ENABLED` off, the backfill cannot read open/close prices; rows stay `settled=FALSE` until enabled, then resolve (or age out to `unresolved` past `ORACLE_HISTORY_WINDOW_SEC`). Provisional `open→now` labels are still written at entry-decision.
- **Settlement timeliness.** `FACTOR_SETTLEMENT_INTERVAL_SEC` (60s) must stay well inside `ORACLE_HISTORY_WINDOW_SEC` (1800s) so a closed candle's open tick still lives in the ring; comfortable margin at defaults.
- **Migration is operator-applied.** The table does not exist until migration 081 runs; the recorder is fail-soft until then (writes log + return False, no scan impact). Consistent with prior lanes ("Operator: apply migration").
- **Per-row grain, not per-(candle,rule).** One row per candle (latest-wins snapshot); `evaluated_rule`/`router_selected_rule` are stored but a candle has a single row. Per-rule granularity, if Phase 2 needs it, is a follow-up (extend the key).
- **DB writes in the scan path.** Throttled + gated + fail-soft, and the candle universe is small (~6 markets), so the added latency is bounded; flagged for the MAJOR validation.

---

## 6. What is next

- WARP🔹CMD review (MAJOR). Operator applies migration 081 and enables `ORACLE_ENABLED` in paper.
- Let the dataset accrue settled `open_to_close` rows across BTC/ETH/SOL × 5m/15m.
- WARP-72 Phase 2 (separate lane): derive scorer weights from the **settled `open_to_close` rows only** — which strategy/factors win under which conditions. Hand-tuned weights remain rejected. Then Phase 3 (shadow A/B vs the precedence router) and Phase 4 (data-gated cutover, router kept as flagged fallback).

---

**Pipeline:** DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION — unchanged; RISK before EXECUTION holds. **Guards:** `ENABLE_LIVE_TRADING` + 13-step risk gate untouched. **Kelly:** untouched (a=0.25). **Concurrency:** asyncio only (recorder/backfill are async; the throttle dict is touched from one event loop).
