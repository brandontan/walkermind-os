# WARP•FORGE — scan-snapshot-capture (WARP-53 Phase-2c-2)

Role: WARP•FORGE (under the WARP•R00T PLAYBOOK epic, WARP-53)
Validation Tier: **STANDARD** (scan-loop telemetry write; gated, fail-soft, no trading effect)
Claim Level: **NARROW INTEGRATION** (one gated hook in the live scan loop; default OFF)
Validation Target: the market-snapshot recorder + its gated, fail-soft scan-loop hook.
Not in Scope: the walk-forward replay engine (Lane 2c-3, consumes this data); per-strategy
universes beyond the shared Gamma fetch (weather/sports orderbook depth — 2c-2b); applying
migration 080 to Supabase (operator); enabling the capture (operator flag).
Suggested Next Step: WARP🔹CMD review/merge; operator applies migration 080 + sets the flag
to begin accrual; then Lane 2c-3 once data has accumulated.

---

## 1. What was built

Phase-2c-2 — the **walk-forward substrate**: the second half of the backtest harness. The
realized-outcome half already exists (`positions.strategy_metadata` for executed trades);
the gap is the **counterfactual** — the full market universe each scan *saw*, including
markets never traded. Without it a replay would be selection-biased (the §12.1 warning).

- **`migrations/080_market_snapshots.sql`** — `market_snapshots` table: per-market
  top-of-book (`best_bid`/`best_ask`/`mid_price`), `liquidity_usdc`, `category`, the full
  upstream dict in `raw` JSONB, linked to `scan_run_id`. Append-only telemetry, no FK into
  trading tables. Indexed on `scanned_at`, `(market_id, scanned_at)`, `scan_run_id`.
- **`domain/research/snapshots.py`** — `record_market_snapshots(run_id, markets)`: a
  defensive Gamma-dict extractor (mid from bid/ask midpoint → `lastTradePrice` →
  `outcomePrices[0]`; tolerant of JSON-string price lists) + a single batched
  `executemany`. Fully fail-soft — any error logs and returns 0, never raising.
- **Scan-loop hook** (`services/signal_scan/signal_scan_job.py`) — one call right after the
  raw Gamma universe is fetched (`_fetch_markets_for_lib_strategies`, **before** any strategy
  filtering → no selection bias), tied to the tick's `scan_run_id`. Gated by
  `SCAN_SNAPSHOT_ENABLED` (default OFF) with the settings read itself wrapped fail-soft
  (mirrors the PLAYBOOK/WEATHER gates). `config.py` gains `SCAN_SNAPSHOT_ENABLED = False`.

## 2. Current system architecture

No change to trading behaviour. When the flag is on, each scan tick appends a snapshot of
the ≤200-market Gamma universe it priced; when off (default), the hook is a single boolean
check. The replay engine (2c-3) will read `market_snapshots` and re-run the *real* signal →
router → gate path over the historical rows — no parallel sim logic, no sim/live drift.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/migrations/080_market_snapshots.sql` — NEW
- `projects/polymarket/crusaderbot/domain/research/snapshots.py` — NEW
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — gated hook
- `projects/polymarket/crusaderbot/config.py` — `SCAN_SNAPSHOT_ENABLED` flag
- `projects/polymarket/crusaderbot/tests/test_research_snapshots.py` — NEW (8 tests)
- `projects/polymarket/crusaderbot/reports/forge/scan-snapshot-capture.md` — this report
- State: `state/PROJECT_STATE.md` · `state/WORKTODO.md` · `state/CHANGELOG.md`

## 4. What is working

- **90 tests pass** (8 new snapshot recorder + 82 signal-scan regression); ruff +
  py_compile clean. Extraction paths (bid/ask mid, lastTradePrice + outcomePrices fallbacks,
  liquidityNum fallback, missing-id → skip) and the writer (run_id prepend, non-dict skip,
  empty → 0, fail-soft on DB error) are pinned.
- The gated settings read is fail-soft, so a Settings/DB failure can never break the scan
  loop (verified — the scan-job regression suite exercises run_once with no env/pool).

## 5. Known issues

- Captures the shared Gamma universe (`get_events_with_markets`, ≤200) — broad and
  cross-category, but per-strategy orderbook-depth snapshots (weather/sports CLOB books)
  are a follow-up (2c-2b) if the replay needs deeper book state than top-of-book.
- Retention is an operator concern (prune `market_snapshots` beyond the backtest horizon);
  documented in the migration, not auto-pruned (no surprise deletes).
- Stacks on PR #1578 (shares the `domain/research/` package); merge order is flexible —
  the two lanes touch disjoint files except the shared package dir.

## 6. What is next

- Operator: apply migration 080 + set `SCAN_SNAPSHOT_ENABLED=true` to begin accrual.
- Lane 2c-3: walk-forward replay engine over `market_snapshots` (§12.1 metrics + leakage/
  overfit/selection-bias detection) once enough history exists.
- Lane 2c-1b: wire the robustness gate (from #1578) into the activation layer.

---

- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION (one gated scan-loop hook, default OFF)
- Validation Target: snapshot recorder + gated fail-soft hook
- Not in Scope: replay engine, per-strategy book depth, migration apply, flag enable
- Suggested Next Step: WARP🔹CMD review/merge → operator enable → Lane 2c-3
