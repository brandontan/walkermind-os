# WARP•R00T REPORT — safe-close-flip-hunter-kreo-parity

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: Realign `safe_close` + `flip_hunter` candle presets to Kreo's reference behaviour (per docs.kreo.app / Telegram bot screenshots). Adds Kreo-style fixed-time exit, flips flip_hunter direction + window, loosens edge filters to Kreo levels. close_sweep unchanged.
Not in Scope: confluence_scalper, lib/ strategies, signal_following feed signals, activation guards, risk gate (13 steps unchanged), schema migrations, exit_watcher non-late_entry paths.
Suggested Next Step: WARP🔹CMD review (Tier MAJOR — touches execution exit path). Optional SENTINEL gate. Source: `projects/polymarket/crusaderbot/reports/forge/safe-close-flip-hunter-kreo-parity.md`.

---

## 1. What was built

Two structural changes plus a new exit mechanism, scoped strictly to the three candle presets driven by `late_entry_v3`.

### A. Strategy params realigned to Kreo

| Preset       | Field                  | Before                                | After (Kreo)                                              |
|--------------|------------------------|---------------------------------------|-----------------------------------------------------------|
| safe_close   | `min_ask_diff`         | 0.08                                  | **0.01** (Kreo Min Edge 1%)                               |
| safe_close   | `force_exit_at_rem_sec`| (none — TP/SL only)                   | **30s** — close BEFORE the noisy final 30s                |
| flip_hunter  | `underdog_mode`        | True (enter cheap side 0.26–0.36)     | **False** (Kreo "With Trend" → favored side)             |
| flip_hunter  | entry window 5m        | rem ∈ (0, 140] (LAST 140s)            | **rem ∈ [160, 300]** (FIRST 140s elapsed)                |
| flip_hunter  | entry window 15m       | rem ∈ (0, 140] (same, tf-unaware)     | **rem ∈ [480, 900]** (FIRST 420s elapsed)                |
| flip_hunter  | `fav_price_min/max`    | 0.26 / 0.36 (cheap-side band)         | **0.50 / 0.95** (favored-side band, skip near-resolved)  |
| flip_hunter  | `min_ask_diff`         | 0.05                                  | **0.03** (Kreo Min Edge 3%)                               |
| flip_hunter  | `force_exit_at_rem_sec`| (none — TP/SL only)                   | **160s (5m) / 480s (15m)** — end of entry window          |
| close_sweep  | all                    | unchanged                             | unchanged (already matches Kreo Close Sweep)             |

### B. Kreo-style fixed-time exit mechanism (NEW)

`late_entry_v3.evaluate_exit()` rewritten as a two-stage gate:

1. **Fixed-time exit** (NEW, runs FIRST): close the position when the candle's remaining seconds drop to `force_exit_at_rem_sec` (≤). Threshold + current rem are passed through the position dict by `exit_watcher`.
2. **Flip-stop** (preserved): existing behaviour — close when favored-side live price ≤ `LATE_ENTRY_FLIP_STOP` (default 0.10).

Both gates safely no-op on missing inputs, so non-candle / older positions keep TP/SL-only semantics.

### C. Per-timeframe parameter resolver (NEW)

`signal_scan_job._resolve_preset_params(preset, timeframe)` is the single source of truth for what each preset+tf combination passes to `scan()`. flip_hunter is the only timeframe-aware preset (Kreo splits its elapsed-time window per candle length: 0–140s for 5m, 0–420s for 15m). safe_close and close_sweep use rem-time semantics identical across timeframes.

Reads live config (env-tunable via Fly secrets), falls back to module-level static literals on config error so test environments without a `.env` still get correct values.

### D. End-to-end wiring

```
scan-time (signal_scan_job.run_close_sweep_fast / run_once Phase B2)
  └─ _resolve_preset_params(preset, tf)
       └─ late_entry_strat.scan(..., force_exit_at_rem_sec=X)
            └─ _evaluate_market emits metadata["force_exit_at_rem_sec"]=X

exit-time (exit_watcher.evaluate -> registry_strategy_evaluator)
  └─ OpenPositionForExit now carries active_preset + selected_timeframe
     (JOIN with user_settings in list_open_for_exit, no migration)
  └─ enriches payload:
       payload["force_exit_at_rem_sec"] = force_exit_at_rem_sec_for(preset, tf)
       payload["seconds_to_close"]      = max(0, resolution_at - now)
       payload["active_preset"]         = position.active_preset
       payload["selected_timeframe"]    = position.selected_timeframe
  └─ late_entry_v3.evaluate_exit
       ├─ fixed-time exit: rem ≤ force_exit_at_rem_sec → STRATEGY_EXIT
       └─ flip-stop: live price ≤ FLIP_STOP_PRICE → STRATEGY_EXIT
```

Risk gate's 13 steps and all 5 activation guards (`ENABLE_LIVE_TRADING`, `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, `RISK_CONTROLS_VALIDATED`, `SECURITY_HARDENING_VALIDATED`) are untouched.

---

## 2. Current system architecture

Pipeline boundary unchanged:

```
DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING
                  │                                  │
                  └── late_entry_v3.scan ──┐         ├── exit_watcher tick (60s)
                       (entry-side gates,  │         │     └── registry_strategy_evaluator
                        emits metadata)    │         │          └── late_entry_v3.evaluate_exit
                                           │         │               1. fixed-time exit ← NEW
                                           │         │               2. flip-stop (existing)
                                           ▼         ▼
                                       SignalCandidate    OpenPositionForExit
                                       .metadata          .active_preset, .selected_timeframe (NEW)
                                         force_exit_at    (JOIN user_settings, no migration)
                                         _rem_sec (NEW)
```

Single source of truth for the (preset, timeframe) → force_exit_at_rem_sec map: `late_entry_v3.force_exit_at_rem_sec_for()`, consumed by both the entry path (via the resolver) and the exit path (via `_late_entry_force_exit_for` in exit_watcher).

---

## 3. Files created / modified

| Action   | Path |
|----------|------|
| Modified | `projects/polymarket/crusaderbot/config.py` (Kreo-aligned per-tf params + force_exit settings) |
| Modified | `projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py` (scan/`_evaluate_market` accept + emit `force_exit_at_rem_sec`; rewritten `evaluate_exit`; new `force_exit_at_rem_sec_for` helper + `_FORCE_EXIT_STATIC` fallback) |
| Modified | `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` (new `_resolve_preset_params(preset, timeframe)`; both call sites refactored; threads `force_exit_at_rem_sec` to scan; `_CANDLE_PRESET_PARAMS` back-compat alias kept) |
| Modified | `projects/polymarket/crusaderbot/domain/positions/registry.py` (`OpenPositionForExit` gains `active_preset` + `selected_timeframe`; SQL pulls them from existing user_settings JOIN) |
| Modified | `projects/polymarket/crusaderbot/domain/execution/exit_watcher.py` (`registry_strategy_evaluator` enriches payload for `late_entry_v3`; two private helpers — `_late_entry_force_exit_for`, `_seconds_to_close_from`) |
| Modified | `projects/polymarket/crusaderbot/tests/test_late_entry_v3.py` (+13 hermetic: metadata emission, evaluate_exit branches, helper lookup) |
| Modified | `projects/polymarket/crusaderbot/tests/test_signal_scan_job.py` (+8 hermetic: `_resolve_preset_params` correctness across both timeframes) |
| Modified | `projects/polymarket/crusaderbot/tests/test_exit_watcher.py` (+6 hermetic: end-to-end fire/hold for safe_close 30s, close_sweep no-force-exit, flip_hunter 5m+15m, missing resolution_at) |
| Created  | `projects/polymarket/crusaderbot/reports/forge/safe-close-flip-hunter-kreo-parity.md` |

No schema migration. No new dependencies.

---

## 4. What is working

- **Full suite green**: 1894 passed / 5 skipped / 0 failures.
- **+27 new hermetic tests** across late_entry_v3, signal_scan_job, exit_watcher.
- `ruff check` clean on all 8 modified files.
- `py_compile` clean on all production files.
- Kreo parity verified end-to-end via test fixtures:
  - `test_registry_evaluator_fires_safe_close_force_exit_when_rem_below_30s` (rem 25s → exit)
  - `test_registry_evaluator_holds_safe_close_when_rem_above_30s` (rem 50s → hold)
  - `test_registry_evaluator_close_sweep_has_no_force_exit` (rem 5s → still hold, tf-invariant)
  - `test_registry_evaluator_fires_flip_hunter_5m_force_exit_at_160s` (rem 155s → exit)
  - `test_registry_evaluator_holds_flip_hunter_15m_above_threshold` (rem 600s → hold)
  - `test_registry_evaluator_no_resolution_at_no_force_exit` (missing rem → flip-stop only)
- Backward compatibility preserved:
  - Positions without `active_preset` / `selected_timeframe` keep existing flip-stop / TP / SL behaviour
  - Non-late_entry strategies see no new payload keys
  - Older `OpenPositionForExit` callers (tests, fixtures) work — both new fields default to None
- `_CANDLE_PRESET_PARAMS` alias kept so external test imports still resolve

---

## 5. Known issues

- **Preset-switch mid-position**: the exit hook looks up `force_exit_at_rem_sec` from the position's CURRENT `active_preset` at every tick (read from user_settings via the JOIN). If a user switches preset while a position is open, the exit rule changes accordingly. For the typical use case (users settle on one preset and run) this is rare; for paper-mode testing it is the desired behaviour (the new rule takes effect immediately). A dedicated "lock preset on position open" design would require a position-level schema column and is out of scope.
- **"Distance" + "Sides" Kreo params not yet mapped**: the docs.kreo.app docs returned HTTP 403 to WebFetch so the precise semantics of "Distance 0.03%–1.00%" + "Sides BOTH/unchanged" remain interpreted. Current implementation keeps our existing `fav_price_min/max` (now 0.60/0.70 for safe_close, 0.50/0.95 for flip_hunter) and side-picking (favored side via majority ask). Owner clarification can tune later as a v2 lane.
- **Single shared FLIP_STOP**: all three candle presets still share `LATE_ENTRY_FLIP_STOP` (currently 0.10 — near-disabled). Per-preset flip-stop tuning is deferred.
- **Trade-rate calibration unverified**: pre-deploy data showed 5.5% of safe_close trades inside the intended band, 47% in coin-flip. Post-deploy, the gate 3c fill-drift guard (PR #1414) + the new force-exit should both reduce bad fills. Actual post-deploy trade rate needs ≥1h observation to validate.

---

## 6. What is next

- WARP🔹CMD review (Tier **MAJOR** — touches execution exit path). Optional SENTINEL gate.
- Fly redeploy. Then observation:
  - Watch new late_entry_v3 positions for `force_exit_at_rem_sec` in metadata + `trigger=fixed_time_exit` in close logs / events.
  - Verify safe_close positions close at rem ≤ 30s (= ~30s hold once entered in the 30–60s window).
  - Verify flip_hunter 5m positions close at rem ≤ 160s (= entered in first 140s, exits at end of window).
  - Confirm close_sweep behaviour unchanged (holds to candle resolution).
- Owner-side validation: subjective Telegram UX check — do `safe_close` + `flip_hunter` now feel like Kreo's namesakes?
- Optional v2 (separate lane): per-preset flip-stop tuning + Kreo "Distance" semantic verification once docs accessible.

---

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
