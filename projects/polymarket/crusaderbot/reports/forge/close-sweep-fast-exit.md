# WARP•R00T FORGE REPORT — close-sweep-fast-exit (PR 2/3 of close_sweep Kreo-parity)

Branch: `WARP/ROOT/close-sweep-fast-exit`
Role: WARP•R00T
Validation Tier: MAJOR (execution loop — exit timing)
Claim Level: NARROW INTEGRATION

## 1. What was built
DEFECT 2 fix: close_sweep now reliably force-exits ~1–8s before a 5-minute
candle resolves (Kreo "exit at 299s"), via a CLOB sell at the live mark, instead
of holding to on-chain resolution where the 30s watcher could miss the price and
mislabel the close as market_expired / 0% PnL. TP/SL still exit earlier if hit.

- New config: PRESET_CLOSE_SWEEP_FORCE_EXIT_REM_SEC=8.0, CLOSE_SWEEP_EXIT_INTERVAL=5, CLOSE_SWEEP_EXIT_NEAR_SEC=90.
- close_sweep added to late_entry_v3 _FORCE_EXIT_STATIC + force_exit_at_rem_sec_for() → returns 8s (5m/15m). Reuses the existing fixed-time exit path (safe_close/flip_hunter use it) in evaluate_exit.
- registry: extracted _row_to_open_position helper; new list_open_candle_positions_for_exit(near_seconds) — scoped SQL (candle presets + resolution_at within N seconds).
- exit_watcher.run_once: new position_loader + run_resolved_phase params (reuses the full evaluate/_act_on_decision close pipeline — no duplicated close logic).
- scheduler: new check_candle_exits driver + close_sweep_exit_fast job (5s). Global 30s exit_watch stays as backstop. Double-close race-safe (atomic status claim in live.close_position).

## 2. Architecture
Two exit loops now share one evaluation path: the global 30s watcher (all
positions, Phase A+B) and the 5s candle loop (scoped near-resolution candle
positions, Phase A only). force_exit_at_rem_sec=8 ≥ 5s interval → the last tick
before resolution always fires.

## 3. Files modified
- config.py (3 new constants)
- domain/strategy/strategies/late_entry_v3.py (_FORCE_EXIT_STATIC + force_exit_at_rem_sec_for close_sweep)
- domain/positions/registry.py (_row_to_open_position helper + list_open_candle_positions_for_exit)
- domain/execution/exit_watcher.py (run_once position_loader + run_resolved_phase)
- scheduler.py (check_candle_exits + close_sweep_exit_fast job)
- tests: test_exit_watcher.py (inverted close_sweep force-exit + holds-above-8s + run_once loader/skip-resolved), test_late_entry_v3.py (close_sweep=8s), test_config_defaults.py, test_close_sweep_fast_exit.py (new), test_daily_pnl_summary/test_lifecycle_ws/test_order_lifecycle (fake-settings attrs)

## 4. What is working
close_sweep force-exits at rem≤8s; holds above; scoped loader + Phase-B skip
verified; scoped SQL filters candle presets + near-window. 6 net-new tests; full
suite 2046 pass; ruff + py_compile clean.

## 5. Known issues
None. PR 3 (min-edge 2–4%) follows.

## 6. What is next
PR 3: randomize close_sweep min_ask_diff 0.02–0.04 (Kreo Min Edge ~2%).
