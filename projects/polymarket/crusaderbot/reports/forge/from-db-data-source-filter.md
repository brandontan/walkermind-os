# WARP-78 — `--from-db` data_source filter (cutover trains on paper_real only)

- Role: WARP•R00T
- Validation Tier: MAJOR (CMD-assigned — gates which rows the cutover model is
  derived from; a wrong filter would train the live cutover on synthetic data).
  Additive + opt-in; dormant until an operator runs `--from-db` (CMD-gated).
- Claim Level: NARROW INTEGRATION (filter wired through the offline model-gen +
  report `--from-db` paths with hermetic tests; not exercised against prod here).
- Validation Target: `ev_comparator --from-db` and `report_cutover_holdout
  --from-db` read ONLY `data_source='paper_real'` rows by default, never the
  `paper_synthetic` seed.
- Not in Scope: running `--from-db` (still CMD-gated, data not ready); the parked
  WARP-72 scorer / A-B paths (left unfiltered, back-compat).
- Branch: `WARP/from-db-data-source-filter`

---

## 1. What was built

The real-data re-run readiness check surfaced that `factor_vectors` still holds
the `paper_synthetic` seed (≈420/419 settled rows per 5m cell) alongside the
accruing `paper_real` rows. `fetch_settled_rows` filtered only
`settled + outcome_source='open_to_close'` — NOT provenance — so
`ev_comparator --from-db` would have derived the "real" cutover model from ~85%
synthetic data. This lane closes that gap using the WARP-77 #1655 `data_source`
enum.

- **`domain/strategy/scorer_trainer.py`** — `fetch_settled_rows(pool=None, *,
  data_source: str | None = None)`. When `data_source` is set, the query appends
  `AND data_source = $1` (parameterized). Default `None` = read every provenance
  (back-compat: the parked WARP-72 `train_from_db` / `scorer_ab` callers are
  unchanged).
- **`domain/strategy/ev_comparator.py`** — `CUTOVER_DATA_SOURCE = "paper_real"`;
  `_fetch_and_derive(..., data_source=CUTOVER_DATA_SOURCE)` passes it through; the
  CLI gains `--data-source {paper_real,paper_synthetic,live_real,all}` defaulting
  to `paper_real` (`all` → no filter). The write log now records
  `data_source` + `rows`.
- **`scripts/report_cutover_holdout.py`** — `CUTOVER_DATA_SOURCE = "paper_real"`;
  `_fetch_real_rows(data_source=...)`; CLI `--data-source` (default `paper_real`,
  `all` → no filter); the rendered header reflects the actual provenance.

## 2. Current system architecture

```
ev_comparator --from-db [--data-source paper_real]   (default paper_real)
report_cutover_holdout --from-db [--data-source ...]  (default paper_real)
        │
        ▼
fetch_settled_rows(data_source="paper_real")
   SELECT … FROM factor_vectors
    WHERE settled=TRUE AND outcome_source='open_to_close'
      AND data_source = $1            ← new, only when data_source is set
        │
        ▼
derive_ev_model(rows)  /  compute_report(rows)   (real rows only)
```

## 3. Files created / modified (full repo-root paths)

- Modified: `projects/polymarket/crusaderbot/domain/strategy/scorer_trainer.py`
- Modified: `projects/polymarket/crusaderbot/domain/strategy/ev_comparator.py`
- Modified: `projects/polymarket/crusaderbot/scripts/report_cutover_holdout.py`
- Created: `projects/polymarket/crusaderbot/tests/test_warp78_from_db_data_source_filter.py`
- Created: `projects/polymarket/crusaderbot/reports/forge/from-db-data-source-filter.md`
- State sync: `state/PROJECT_STATE.md`, `state/CHANGELOG.md`

## 4. What is working

6 hermetic tests (fake asyncpg pool captures SQL + bound args):
- `data_source="paper_real"` → query contains `data_source = $1`, args `("paper_real",)`.
- `data_source=None` and the default → no provenance predicate (back-compat).
- fail-soft → `[]` on a bad pool.
- `ev_comparator.main(["--from-db"])` passes `paper_real`; `--data-source all` → None.
- `report_cutover_holdout._fetch_real_rows()` defaults to `paper_real`.

`ruff` clean. Regression: `test_warp78_ev_comparator` + `test_cutover_report_template`
still pass. (`test_warp72_scorer` import-fails only in the dep-less local sandbox —
`telegram` not installed — and is green in CI; unaffected by this change.)

The filter matches the live DB: a direct provenance count confirms
`paper_real` settled OTC rows are BTC/5m=77, ETH/5m=75, BTC/15m=13, ETH/15m=11
(vs ~420/419/84/82 `paper_synthetic`), so the filter changes the cutover input
materially.

## 5. Known issues

- The cutover model file is still NOT generated — `--from-db` stays CMD-gated and
  the data is not ready (paper_real far below the ≥200/cell minimum; see the 15m
  accrual investigation lane).
- Pre-#1655 historical rows default to `paper_synthetic` (NOT NULL DEFAULT); the
  filter correctly excludes them — only rows the provenance writer stamped
  `paper_real` are trained on.

## 6. What is next

- Lane 2: `WARP/15m-accrual-investigation` (report-only) — why the 15m cells stalled.
- When 5m ≥200/cell AND CMD reviews the 15m findings: `ev_comparator --from-db`
  (now paper_real-only) → `report_cutover_holdout --from-db --margin 0.015` →
  §1.7 verdict → CMD cutover decision.

Suggested Next Step: WARP🔹CMD review; this must land before the real re-run.
