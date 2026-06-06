# WARP-77 Phase 1.4 — factor_vectors provenance column (`data_source`)

- Role: WARP•R00T
- Validation Tier: MAJOR (DB migration + scan-path persistence writer) — but additive,
  dormant (column read by NOTHING; no gate/selection/risk/execution path consumes it),
  and fail-soft. Merged under WARP•R00T merge authority; dormancy proven below.
- Claim Level: NARROW INTEGRATION
- Validation Target: every `factor_vectors` row carries a non-NULL `data_source`
  provenance tag; new rows are stamped from the runtime data regime; existing rows
  backfill to `paper_synthetic`.
- Not in Scope: any read/consumer of `data_source` (downstream WARP-78 filtering is
  separate), the real-CLOB cutover itself (operator `fly secrets set USE_PYSDK_CLOB=true`),
  applying the migration to prod (deploy = operator-owned; auto-applies via `run_migrations`).
- Branch: `WARP/root-factor-vectors-provenance`

---

## 1. What was built

A provenance column on `factor_vectors` so paper-on-synthetic, paper-on-real-CLOB,
and live-on-real-CLOB samples are separable downstream (WARP-78 must not mix
synthetic and real-CLOB rows when it iterates the strategy on real data):

- **Migration `083_factor_vectors_data_source.sql`** — adds enum type
  `factor_data_source ('paper_synthetic'|'paper_real'|'live_real')` and column
  `factor_vectors.data_source NOT NULL DEFAULT 'paper_synthetic'`, plus an index.
  Idempotent (guarded `CREATE TYPE` / `ADD COLUMN IF NOT EXISTS`) — safe to re-run
  on every boot, which is exactly how `run_migrations()` applies it.
- **Rollback `migrations/rollback/083_factor_vectors_data_source_rollback.sql`** —
  drops index → column → type. Lives OUTSIDE the `migrations/*.sql` top-level glob
  (`run_migrations` is non-recursive), so it is never auto-executed; apply manually
  to revert.
- **Writer (`domain/research/factor_dataset.py`)** — `resolve_data_source(settings)`
  maps the runtime regime to the tag: real LIVE posture → `live_real`
  (reuses the canonical `config.resolve_trading_mode`, i.e. ALL THREE guards open:
  `ENABLE_LIVE_TRADING` + `EXECUTION_PATH_VALIDATED` + `CAPITAL_MODE_CONFIRMED` —
  `ENABLE_LIVE_TRADING` alone is still PAPER and must not be tagged live); else
  `USE_PYSDK_CLOB → paper_real`; else `paper_synthetic`. Fail-soft to
  `paper_synthetic`. `record_factor_vector` appends the tag as the final INSERT
  column and refreshes it on the latest-wins UPSERT.

## 2. Current system architecture

Unchanged pipeline. `factor_vectors` remains the shadow telemetry sink
(`record_factor_vector` at the entry-decision point; `backfill_factor_settlement`
resolves open→close). The only delta is one additional provenance column written
alongside the existing 34. Settlement / router-mark UPDATEs do not touch it.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/migrations/083_factor_vectors_data_source.sql` (new)
- `projects/polymarket/crusaderbot/migrations/rollback/083_factor_vectors_data_source_rollback.sql` (new)
- `projects/polymarket/crusaderbot/domain/research/factor_dataset.py` (modified — provenance resolver + INSERT column)
- `projects/polymarket/crusaderbot/tests/test_warp77_data_source.py` (new — 8 hermetic tests)
- `projects/polymarket/crusaderbot/reports/forge/warp77-factor-provenance.md` (this report)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` + `state/CHANGELOG.md` (sync)

## 4. What is working

- **Acceptance is structurally guaranteed**: `NOT NULL DEFAULT 'paper_synthetic'`
  backfills every existing row (the 797 settled + all unsettled) and every future
  INSERT that omits the column → **no NULL possible**. New rows under the new writer
  are stamped explicitly.
- **Arg-alignment**: `_INSERT_COLS = _COLS + ('data_source',)`, placeholder count =
  `len(_INSERT_COLS)`, execute passes `*_row(fv), data_source` — equal by construction.
  `py_compile` clean on the module + test; verified by an isolated harness
  (full pytest deps unavailable in the sandbox — runs in CI).
- **Forward/backward compatible**: the currently-deployed OLD writer (no `data_source`
  in its INSERT) keeps working once the column exists — the DEFAULT applies, so the
  column can be added to prod independently of the code deploy with zero breakage.

## 5. Known issues

- None introduced. `data_source` has no consumer yet (deliberate — WARP-78 reads it
  later). The prod apply happens on the next deploy via `run_migrations()`
  (operator-owned); direct prod application was intentionally not forced.

## 6. What is next

- Operator deploys → `run_migrations()` applies `083` (idempotent). Verify
  `SELECT data_source, count(*) FROM factor_vectors GROUP BY 1` shows all
  `paper_synthetic` pre-cutover, then `paper_real` accruing after
  `USE_PYSDK_CLOB=true` (WARP-77 Phase 1.2).
- WARP-78 Phase 1 later filters its shadow analysis to `paper_real` rows only.

- Suggested Next Step: pair with WARP-77 Phase 1.2 (real-CLOB cutover doc +
  heartbeat) so provenance + real-data feed land together before WARP-78 Phase 1.
