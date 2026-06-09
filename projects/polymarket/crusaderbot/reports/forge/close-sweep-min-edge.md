# WARP•R00T FORGE REPORT — close-sweep-min-edge (PR 3/3 of close_sweep Kreo-parity)

Branch: `WARP/ROOT/close-sweep-min-edge`
Role: WARP•R00T
Validation Tier: STANDARD (entry threshold tuning — user-facing trade frequency)
Claim Level: NARROW INTEGRATION

## 1. What was built
Operator decision: close_sweep "Min Edge" follows Kreo (~2%), randomized 2–4%
per scan (looser than the old fixed 0.05 → more entries, still skips coin-flips).

- New config PRESET_CLOSE_SWEEP_MIN_ASK_DIFF_MIN=0.02 / _MAX=0.04.
- New helper _random_close_sweep_min_edge(cfg): draws min_ask_diff in [MIN,MAX]
  per scan; MIN==MAX pins it (deterministic); never raises (fallback 0.02).
- close_sweep branch of _resolve_preset_params uses the randomized value.
- import random added to signal_scan_job.

## 2. Architecture
Per-scan entry threshold only; no change to exit/TP/SL/price logic.

## 3. Files modified
- config.py (MIN/MAX band)
- services/signal_scan/signal_scan_job.py (import random + _random_close_sweep_min_edge + close_sweep resolver)
- tests/test_signal_scan_job.py (band + pinned + fallback + resolver-in-band tests)
- tests/test_config_defaults.py (band defaults)

## 4. What is working
min_ask_diff randomized within [0.02,0.04]; pinned when MIN==MAX; safe fallback.
Full suite 2045 pass; ruff + py_compile clean.

## 5. Known issues
None. Final PR of the close_sweep Kreo-parity trio.

## 6. What is next
WARP🔹CMD review + merge → re-enable live (Step 0 reverse) → small-cap live test.
