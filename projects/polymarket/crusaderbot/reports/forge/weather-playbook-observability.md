# WARP-80 sub-lane 1a — Weather + Playbook scan observability

Role: WARP•R00T (observability instrumentation — additive, no behaviour change)
Validation Tier: **MINOR** (observability-only; no selection/threshold/risk change)
Claim Level: **NARROW INTEGRATION** (instruments the live weather + playbook scan
paths + a new persistence table; wired into `signal_scan_job.run_once`)
Validation Target: per-scan-tick capture of weather + playbook near-miss /
abstain readings (distance-to-threshold, would-pass-at-relaxed-threshold, feed
state) into a queryable DB table, so sub-lane 1b can do threshold tuning without
Fly DEBUG-log access.
Not in Scope: any threshold change (1b recommends, CMD decides); external-feed
wiring (1c, deferred); ev_comparator / scorer_trainer / orchestrator (WARP-79);
late_entry_v3 instrumentation.
Suggested Next Step: WARP🔹CMD review (MINOR). After ~24h of accrual, run the 1b
refresh against `strategy_scan_observations` for sharp threshold recommendations.

---

## 1. What was built

Per-scan-tick near-miss instrumentation for the two opportunistic strategies that
book zero entries by design (`weather`, `playbook`). For every market that reaches
a binding edge filter, the strategy now records HOW FAR it was from passing and
whether it WOULD pass at relaxed thresholds (−10% / −25% / −50%), plus the live vs
dark feed state. Rows land in a new append-only `strategy_scan_observations` table.

This closes the observability gap named in the #1664 investigation §6: today the
binding constraint (no-feed vs EV-too-low vs price-too-high vs no-in-window-market)
lives only in DEBUG logs (`weather_city_scan_result`), invisible without Fly log
access. The fields the spec required are now in the DB and queryable:
`strategy`, `observed_at`, `market_id`, `zero_reason`, `distance_to_threshold`,
`would_pass_at_threshold` (struct over the 3 levels), and `module_state`.

Persistence choice — **Supabase table, not Sentry**: the volume is tiny (weather
dispatches in ~33% of ticks / playbook ~7%, both 0-yield; structurally-eligible
markets per tick are bounded ≪ the 1MB/hr stop-threshold), and 1b must *aggregate
distributions* of `distance_to_threshold` — queryable SQL rows beat Sentry events.
Mirrors the existing `scan_runs` / `market_snapshots` telemetry pattern.

## 2. Current system architecture

No trading/selection/threshold/risk change. The flow is additive and fully
fail-soft:

```
signal_scan_job.run_once
  ├─ (after market fetch) begin_sink()           # ContextVar list, gated default ON
  ├─ per-user loop → weather_strat.scan() ──┐
  │                  playbook_strat.scan() ─┤ record_observation(ScanObservation)
  │     (weather fans out per city via       │  appended to the active sink; no-op
  │      asyncio.gather — child tasks copy    │  if no sink open. Wrapped try/except.
  │      the ContextVar, so the shared sink   │
  │      sees every city's rows)             ─┘
  └─ (before _finish_scan_run) drain_sink() → record_scan_observations(run_id, rows)
                                              # one batched, append-only INSERT
```

The sink is a `contextvars.ContextVar` so it needs **no new parameter on
`BaseStrategy.scan`** and is async-safe across `asyncio.gather` fan-out. Every
public function in the module is fail-soft; a recording or write error is
swallowed and never reaches the scan/selection path. A `SCAN_OBSERVABILITY_ENABLED`
config flag (default ON) is the no-redeploy Fly-secret kill if volume ever spikes.

Instrumentation points (the binding edge filters only — structural pre-filters are
left untouched):
- **Weather** `domain/strategy/strategies/weather.py`: price-ceiling fails
  (`binding_filter="price"`, ceiling-relax map) and the EV gate for every
  structurally-eligible market, pass or fail (`binding_filter="ev"`, floor-relax
  map) — giving 1b the full EV distribution vs `min_ev`.
- **Playbook** `domain/strategy/strategies/playbook.py`: quality reject
  (`binding_filter="quality"`) and router abstain (`binding_filter="router_abstain"`),
  each stamped with `module_state` (`null_feed` when the default `NullFeed` darkens
  injury_alpha + public_fade, else `live`).

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/migrations/086_strategy_scan_observations.sql` — new table + 3 indexes + RLS deny-by-default
- `projects/polymarket/crusaderbot/domain/research/scan_observability.py` — dataclass, threshold math, ContextVar sink, fail-soft writer
- `projects/polymarket/crusaderbot/tests/test_scan_observability.py` — 11 hermetic tests
- `projects/polymarket/crusaderbot/reports/forge/weather-playbook-observability.md` — this report

Modified:
- `projects/polymarket/crusaderbot/config.py` — `SCAN_OBSERVABILITY_ENABLED: bool = True`
- `projects/polymarket/crusaderbot/domain/strategy/strategies/weather.py` — EV + price gate observations (fail-soft)
- `projects/polymarket/crusaderbot/domain/strategy/strategies/playbook.py` — quality + router-abstain observations (fail-soft)
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — import alias + per-tick sink begin/drain/persist
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `state/CHANGELOG.md` — synced

## 4. What is working

- 11/11 new unit tests pass; `ruff` clean on all changed files; `py_compile` clean.
- Threshold math verified at all 3 relax levels for both floor (`min_ev`) and
  ceiling (`max_price`) gates, plus signed-distance correctness.
- Sink lifecycle verified: collects under an open sink, no-op without one, drain
  resets, and a fresh `begin_sink` never inherits a prior un-drained tick's rows.
- Writer verified against a fake asyncpg pool (SQL + JSONB serialization captured)
  and fail-soft on pool error (returns 0, never raises) + drops rows missing a
  `market_id`.
- Existing `test_playbook_engine.py` is SKIPPED in this dev-light env by the repo's
  documented optional-dep guard (`httpx` not installed; CI installs the full
  stack) — not a regression from this lane.

## 5. Known issues

- `distance_to_threshold` / `would_pass_at_threshold` are populated for weather
  (the EV + price edge gates). For playbook the meaningful signal is feed darkness,
  so its observations carry `module_state` + `zero_reason` with numeric distance
  left NULL — a per-module edge-distance (e.g. closing_edge vs `CLOSING_EDGE_MIN_EDGE`)
  would require touching `domain/playbook/modules.py` and is a deliberate
  follow-up, not in this lane.
- The new table needs migration 086 applied to prod (operator-owned, runs on next
  deploy via `run_migrations`); until then the fail-soft writer logs + returns 0.
- Volume guard is the static `SCAN_OBSERVABILITY_ENABLED` Fly-secret flag (not yet
  runtime_config-wired); a no-redeploy DB toggle is a trivial follow-up if needed.

## 6. What is next

1. WARP🔹CMD review (MINOR tier).
2. Apply migration 086 on deploy; confirm `strategy_scan_observations` accrues
   rows + verify ~1MB/hr stop-condition is not tripped.
3. After ~24h accrual, run the **1b refresh** against the new table for sharp
   per-strategy/threshold recommendations (entry counts at −10/−25/−50%).

---

Validation Handoff (NEXT PRIORITY):

```
WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/weather-playbook-observability.md
Tier: MINOR
```
