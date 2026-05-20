# Forge Report — strategy-pipeline-user-filter

**Branch:** `WARP/strategy-pipeline-user-filter`
**Issue:** #1195 (WARP-44)
**Date:** 2026-05-20 19:00 Asia/Jakarta
**Validation Tier:** STANDARD
**Claim Level:** MODERATE
**Validation Target:** `run_once()` produces per-user filtered candidates; `strategy_params` passed through to `strategy.initialize()`
**Not in Scope:** Telegram UI for strategy_params editing, logic_arb / sentiment / weather_arb, market_making, `user_strategies.params_json`

---

## 1. What was built

Per-user category filter and strategy_params wire-up for the lib-strategy scan loop.

**Three changes delivered:**

- **Migration 043** — `strategy_params` JSONB column added to `user_settings` with default `'{}'`. Stores per-strategy param overrides keyed by strategy name (e.g. `{"momentum": {"drop_threshold": -0.15}}`).
- **`_filter_markets_by_category()`** — new pure helper that filters the full Gamma market list to only the user's chosen categories. Match is substring-based (case-insensitive) against `category`, `groupItemTitle`, or `slug`. Empty `category_filters` list returns all markets unchanged.
- **`run_once()` restructured** — Phase A (run all strategies once globally) and Phase B (distribute per user) merged into a single per-user loop. Markets fetched once from Gamma API; each user's market list is filtered by `category_filters` before being passed to each permitted lib strategy. `strategy_params` for the specific strategy are forwarded as `config` so `strategy.initialize()` receives the user's overrides (e.g. `drop_threshold`, `min_liquidity`). `_load_enrolled_users()` SELECT extended to include both `strategy_params` and `category_filters`.

---

## 2. Current system architecture

```
DATA:        Gamma API → get_markets(limit=200)
              ↓ fetched once per tick
FILTER:      _filter_markets_by_category(markets, user.category_filters)
              ↓ per-user subset (empty = all)
STRATEGY:    run_lib_strategy(lib_name, user_markets, config={"strategy_params": user_params[lib_name]})
              ↓ strategy.initialize(user_params) + strategy.scan(filtered_markets)
INTELLIGENCE: SignalCandidate[] with confidence score
              ↓
RISK:        existing TradeEngine gate (unchanged)
              ↓
EXECUTION:   paper fill (unchanged)
              ↓
MONITORING:  job_runs + positions (unchanged)
```

`pipeline.strategy_scan_done` event now emitted once after all users are processed (was: after Phase A). `total_signals` reflects the aggregate across all users × all strategies.

---

## 3. Files created / modified

| File | Change |
|------|--------|
| `projects/polymarket/crusaderbot/migrations/043_strategy_params.sql` | NEW — adds `strategy_params` JSONB to `user_settings` |
| `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` | MODIFIED — `_load_enrolled_users` SELECT, `_filter_markets_by_category` helper, `run_once` restructure |
| `projects/polymarket/crusaderbot/tests/test_signal_scan_job.py` | MODIFIED — 9 unit tests for `_filter_markets_by_category` |

`lib_strategy_runner.py` — no change required. `strategy.initialize(config.get("strategy_params", {}))` already present at line 245; config dict is already accepted as third arg to `run_lib_strategy`.

---

## 4. What is working

- `_filter_markets_by_category` verified against 9 cases: empty filter, single filter, multi-filter, case-insensitive match, partial substring match, groupItemTitle fallback, slug fallback, no match, empty market list.
- `run_once` per-user loop: markets fetched once, filtered per user, strategy run with user config, per-candidate exception isolation preserved.
- `_load_enrolled_users` returns `strategy_params` and `category_filters` columns.
- `compileall` clean on both modified files.
- Existing preset isolation tests (whale_mirror, contrarian, ensemble, full_auto, None, unknown) continue to pass — loop restructure preserves `_preset_allows()` gate unchanged.

---

## 5. Known issues

- `strategy_params` migration (043) must be applied to Supabase before deploy. One-liner: `ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS strategy_params JSONB DEFAULT '{}';`
- `category_filters` column on `user_settings` confirmed in DB schema per issue spec; no migration needed for it.
- Full integration test suite blocked in cloud execution environment (missing C extensions: cffi/cryptography). Compile-check and isolated function tests pass; full pytest suite requires local environment or CI.
- `pipeline.strategy_scan_done` event timing change (was: post-Phase-A; now: post-all-users). Downstream MONITORING consumers relying on this event's timing may observe it later in the tick. No capital impact.

---

## 6. What is next

- WARP🔹CMD review required. Tier: STANDARD.
- Apply migration 043 to Supabase production before Fly.io redeploy.
- Optional future lane: Telegram UI for `strategy_params` editing (excluded from this scope per issue spec).
- Optional future lane: wire `user_strategies.params_json` into lib runner (separate task).

---

**Suggested Next Step:** WARP🔹CMD review → apply migration 043 → deploy.
