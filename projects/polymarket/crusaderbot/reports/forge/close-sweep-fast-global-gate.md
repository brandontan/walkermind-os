# WARP•R00T FORGE REPORT — close-sweep-fast-global-gate

Branch: `WARP/ROOT/close-sweep-fast-global-gate`
Role: WARP•R00T (owner-reported: admin OFF but strategy still ran)
Validation Tier: MAJOR (global kill-switch leak on the live candle execution loop)
Claim Level: NARROW INTEGRATION

## 1. What was fixed
Bug (owner screenshot): admin toggled `late_entry_v3` OFF in the Ops Console
global on/off, but Close Sweep still showed/traded on the user side.

Root cause: only the 180s `run_once` loop honoured the global disable
(_refresh_disabled_strategies + _preset_allows). The dedicated high-frequency
`run_close_sweep_fast` loop (~15s) — which is what actually executes the candle
presets close_sweep/safe_close/flip_hunter (all route to late_entry_v3) — had
its OWN dispatch and never consulted the global switch. So a globally-disabled
late_entry_v3 kept trading via the fast loop. DB showed strategies.late_entry_v3
= false (toggle persisted), but the fast loop ignored it.

Fix: `run_close_sweep_fast` now calls `_refresh_disabled_strategies()` at the
top and returns early (no users loaded, no scan) when `late_entry_v3` is in the
globally-disabled set. All candle presets route to late_entry_v3, so this stops
every candle entry. Fail-safe: a DB blip keeps the previous set.

Also (UX): clarified the admin help text — a global OFF stops new trades but does
NOT change a user's selected preset, so their dashboard may still show the preset
as active while no new trades fire. (The "ACTIVE" badge reflects the user's preset
choice, which is a separate concept from the global kill-switch.)

## 2. Files modified
- services/signal_scan/signal_scan_job.py (run_close_sweep_fast: global-disable refresh + early return)
- webtrader/frontend/src/pages/AdminPage.tsx (clarify global-toggle help text)
- tests/test_signal_scan_job.py (+1: fast loop skips when late_entry_v3 globally disabled)

## 3. What is working
Toggling late_entry_v3 OFF now halts the fast candle loop (verified by test);
run_once already gated. 4 fast-loop tests pass; full suite 2052; ruff + tsc + vite clean.

## 4. Known issues
User dashboard still shows the user's selected preset as "ACTIVE" while globally
OFF — intended (preset selection ≠ global kill-switch); help text now explains it.

## 5. What is next
WARP🔹CMD review + merge → deploy.
