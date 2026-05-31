# WARP•FORGE — weather-high-water-tracker

## 1. What was built

Runtime high-water (peak price) tracking for weather positions, which
activates **Exit 2 (trailing-stop breakeven)** — the last dormant weather
exit. The weather strategy's `evaluate_exit` already reads
`position.get("high_water_price")` to decide whether a position that once ran
+20% above entry has since fallen back below breakeven, but nothing was
persisting that peak. This lane adds the write surface and wires it into the
exit-watcher tick.

`high_water_price` is a runtime-tracked value (the highest live mark seen
since entry across watcher ticks), not a scan-time snapshot — so it could not
be carried by the signal-time `strategy_metadata` chain shipped in
WARP/weather-strategy-metadata (#1524). This lane closes that gap by writing
the peak back into the same `positions.strategy_metadata` JSONB column on each
held tick, where the existing weather payload spread reads it back on the next
tick.

No new migration — reuses `positions.strategy_metadata` (migration 076).

## 2. Current system architecture

```
exit_watcher.run_once() tick
  └─ evaluate(position)                       # Exit 2 reads high_water_price
        │                                        (loaded from strategy_metadata
        │                                         spread → payload on THIS tick)
        ▼ hold (no exit)
  _act_on_decision(position, hold_decision)
  └─ registry.update_current_price(...)        # live mark + unrealised P&L
  └─ if strategy_type == "weather":
        registry.bump_high_water_price(id, user_id, current_price)
          └─ UPDATE positions
               SET strategy_metadata =
                     COALESCE(strategy_metadata,'{}'::jsonb)
                     || jsonb_build_object('high_water_price', $1::float8)
             WHERE id=$2 AND user_id=$3
               AND $1 > COALESCE((strategy_metadata->>'high_water_price')::float8, 0)
        │
  ── next tick ──
  registry.list_open_for_exit() → _loads_jsonb(strategy_metadata)
  └─ OpenPositionForExit.strategy_metadata{high_water_price, city, bucket...}
        └─ registry_strategy_evaluator weather payload spread
              └─ WeatherDomainStrategy.evaluate_exit → Exit 2 fires when
                 high_water >= entry*1.20 and current_price < entry
```

The bump is a **single atomic statement** with an only-raises guard:
* `$1 > COALESCE(stored, 0)` → a flat / falling market is a no-op (zero wasted
  writes); a concurrent tick can never lower a higher peak.
* `||` merge over `COALESCE(strategy_metadata, '{}'::jsonb)` preserves the
  existing scan-time keys (city / bucket_low / bucket_high / mean_tmax_f) and a
  NULL legacy column is seeded with a fresh object.
* Degenerate prices (None / <= 0) short-circuit before a connection is even
  acquired — a 0-or-below mark is never a valid peak.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/domain/positions/registry.py`
  — new `bump_high_water_price(position_id, user_id, price)` atomic only-raises JSONB merge
- `projects/polymarket/crusaderbot/domain/execution/exit_watcher.py`
  — `_act_on_decision` hold branch calls `bump_high_water_price` for `strategy_type == "weather"` after the `update_current_price` refresh; bump failure caught + logged (never poisons the hold path)
- `projects/polymarket/crusaderbot/tests/test_weather_high_water_tracker.py` (new) — 7 hermetic tests
- `projects/polymarket/crusaderbot/reports/forge/weather-high-water-tracker.md` (this file)

## 4. What is working

- 7 new hermetic tests pass: degenerate-price guards (None / 0 / negative never
  acquire a connection), conditional-merge SQL source pin (high_water_price +
  jsonb_build_object + COALESCE seed + `$1::float8 >` only-raises guard + arg
  order), bump-for-weather-hold, no-bump-for-non-weather, bump-failure-non-fatal,
  watcher gate source pin.
- 68 neighbor regression tests pass (test_weather_strategy_metadata + test_exit_watcher).
- `ruff check` + `py_compile` clean on both modified files + the new test.
- Exit 2 (trailing-stop breakeven) now has its `high_water_price` input wired
  end-to-end. With this lane, **all 5 weather exits are active**: Exit 1 (hard
  stop), Exit 2 (trailing stop — this lane), Exit 3 (tp_48h / tp_48h_plus),
  Exit 4 (adaptive forecast-shift — #1524), Exit 5 (near-expiry).
- Additive + idempotent: non-weather positions unchanged (price refresh only,
  no extra write); only-raises guard means re-running a tick never corrupts the
  peak.

## 5. Known issues

- **One-tick lag (inherent, acceptable).** The peak written on tick N's hold is
  read by Exit 2 on tick N+1 — the current tick's price is not part of its own
  high-water comparison. At the 30s poll interval this is the correct trade-off
  (the alternative would be a second per-tick read-modify-write before
  evaluate). A price that both peaks and crashes inside one 30s window will not
  trigger the trailing stop — documented, not a defect.
- **Paper-path only.** The bump fires from the exit-watcher hold branch, which
  serves paper positions; the live execution path is guard-gated OFF and weather
  is paper-only posture, so live-path high-water persistence is intentionally
  out of scope.

## 6. What is next

- Operator: ensure migration 076 is applied to Supabase (already required by
  #1524) — this lane adds no new migration.
- WARP•SENTINEL validation (MAJOR — touches the exit-watcher execution loop +
  a position write surface) before merge.

---

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: high_water_price runtime persistence (exit_watcher hold branch → registry.bump_high_water_price atomic JSONB only-raises merge → next-tick payload spread) + weather Exit 2 activation
Not in Scope: live-path high-water persistence, sub-poll-interval peak capture, weather forecast/calibration internals, the scan-time metadata chain (shipped in #1524)
Suggested Next Step: WARP•SENTINEL validation (MAJOR tier — execution loop + position write) before merge
