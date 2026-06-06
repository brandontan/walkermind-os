# WARP-78 Phase 1 (down-payment) — real realized-volatility factor (shadow)

- Role: WARP•R00T
- Validation Tier: MAJOR (touches the late_entry_v3 entry path + a migration) — but
  SHADOW-only/additive: the new factor is computed, logged, and persisted as
  telemetry; it is NOT routed/selected/sized, and the entry gates are untouched.
- Claim Level: NARROW INTEGRATION
- Validation Target: replace the dead per-asset constant `volatility_sigma` with a
  REAL rolling realized-volatility measure, emitted as a new scorable factor for
  WARP-78 Phase 1 to correlate against realized EV.
- Not in Scope: routing/selection on the new factor (deliberately shadow — the
  precedence router still controls selection), the EV-comparator (Phase 2), and the
  7-day correlation conclusion (needs accrued shadow data).
- Branch: `WARP/root-realized-volatility-factor`

---

## 1. What was built

Phase 0 found Volatility is **dead** in the model: `volatility_sigma` is a per-asset
config constant (`config.oracle_sigma_per_sqrt_sec`), so its cell std collapses to
~0 and the trainer zeroes its weight. This lane adds a **real** volatility signal:

- **`domain/signal/momentum.py`** — `compute_realized_vol(samples, window_sec, now)`:
  pure rolling realized-variance estimator `sigma = sqrt(Σ rᵢ² / Σ dtᵢ)` over the
  consecutive log-returns of the price ring (units: per-sqrt-second, directly
  comparable to `volatility_sigma`). Needs ≥3 in-window samples (≥2 returns);
  otherwise `None` (honest "not enough history", never a fabricated zero). A flat
  series yields exactly `0.0`. `MomentumTracker.realized_vol(key, now)` reads the
  SAME per-market YES-mid ring momentum already populates — no new data source.
- **`domain/signal/factors.py`** — `FactorVector.realized_vol` (new optional field;
  flows through `to_metadata()`/`emit()` which are generic over `__dict__`).
- **`domain/strategy/strategies/late_entry_v3.py`** — `_observe_factor_vector`
  computes `rvol = tracker.realized_vol(mkt_key, now)` and stamps it on the vector.
- **`migrations/084_factor_vectors_realized_vol.sql`** (+ rollback) — additive,
  nullable `realized_vol NUMERIC(18,10)` column; idempotent.
- **`domain/research/factor_dataset.py`** — `realized_vol` added to the INSERT/UPSERT
  column set (latest-wins refresh, like the other factors).

## 2. Current system architecture

Unchanged selection/risk/execution. The factor-vector shadow pipeline
(`_observe_factor_vector` → `record_factor_vector`) now carries one more measured
factor. The precedence router still controls selection; nothing consumes
`realized_vol` for routing (that is Phase 2's EV-comparator, deliberately not built).

## 3. Files created / modified

- `domain/signal/momentum.py` (+ `compute_realized_vol` + `MomentumTracker.realized_vol`)
- `domain/signal/factors.py` (+ `FactorVector.realized_vol`)
- `domain/strategy/strategies/late_entry_v3.py` (compute + stamp)
- `migrations/084_factor_vectors_realized_vol.sql` (+ `migrations/rollback/084_*`)
- `domain/research/factor_dataset.py` (writer column)
- `tests/test_warp78_realized_vol.py` (new, 7 tests) + `tests/test_warp72_factor_dataset.py` (col count 35→36)
- `reports/forge/warp78-realized-volatility.md` (this) + state sync

## 4. What is working

- `compute_realized_vol` validated by an isolated harness: insufficient→None,
  flat→0.0, positive movement→positive, **per-sqrt-second scaling** (same returns
  over 10× the interval → ~⅓ the sigma: 0.0099 → 0.0031), window filtering,
  non-positive-dt skipped, tracker ring readout. `py_compile` clean on all touched
  files; full pytest in CI.
- Additive + shadow: the entry path's gates/sizing are untouched; the FactorVector
  is telemetry. The new column is nullable (NULL until ≥3 samples accrue).

## 5. Known issues

- This measures the **YES-mid** realized vol (the tradeable instrument), an entry-
  available proxy for the underlying regime — not the Chainlink underlying vol. It
  is the correct "volatility for selection" signal (volatility of what we trade) and
  fixes Phase 0's dead-constant finding; an underlying-vol variant from the oracle
  ring is a possible follow-up.
- The **correlation-with-EV** conclusion (Phase 1 item 6) needs accrued shadow data
  (and is most meaningful on real-CLOB-data rows post-cutover — see WARP-77
  Phase 1.2 + the `data_source` provenance column).
- Per Phase 0, a proper EV-comparator (Phase 2) should also fix the realized-EV
  **label** (force-exit vs hold-to-settlement) — out of scope here.

## 6. What is next

- Operator deploys → migration 084 applies via `run_migrations`; `realized_vol`
  accrues. After the WARP-77 cutover, filter to `data_source='paper_real'` rows and
  document `realized_vol` vs realized EV (Phase 1 item 6) for CMD before any Phase 2
  selector.

- Suggested Next Step: let `realized_vol` accrue alongside the WARP-77 cutover, then
  run the vol↔EV correlation as the Phase 1 exit deliverable for CMD review.
