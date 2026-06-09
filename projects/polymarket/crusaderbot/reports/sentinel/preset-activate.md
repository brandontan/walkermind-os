# WARP•SENTINEL REPORT — preset-activate

Verdict: APPROVED
Score: 91/100
Critical Issues: 0
Branch: WARP/R00T-preset-activate
Source Forge Report: projects/polymarket/crusaderbot/reports/forge/preset-activate.md
Role: WARP•R00T (SENTINEL + FORGE combined authority)

---

## PHASE 0 — Pre-Test

| Check | Result |
|---|---|
| Report at correct path with all 6 sections + metadata | PASS |
| PROJECT_STATE.md updated (NEXT PRIORITY = SENTINEL gate) | PASS |
| No phase*/ folders | PASS |
| Hard-delete policy — no files deleted | PASS |
| Implementation evidence exists for all critical behaviors | PASS |

Phase 0: ALL PASS — proceeding to validation.

---

## PHASE 1 — Functional Testing

### 1A. min_entry_sec floor gate (safe_close)

Code: `late_entry_v3._evaluate_market()` lines 419–424

```python
if min_entry_sec is not None and seconds_left < min_entry_sec:
    return None, "inside_min_entry_sec"
```

Gate sequence for safe_close (entry_window_sec=60, min_entry_sec=30):
- seconds_left=10: passes outer gate (10 ≤ 60) → REJECTED by floor gate (10 < 30) ✓
- seconds_left=45: passes outer gate (45 ≤ 60) → passes floor gate (45 ≥ 30) → ENTERS ✓
- seconds_left=65: REJECTED by outer gate (65 > 60) ✓
- close_sweep (min_entry_sec=None): floor gate skipped entirely ✓

Tests:
- `test_safe_close_skips_when_inside_min_entry_sec` PASS
- `test_safe_close_enters_within_valid_window` PASS

### 1B. underdog_mode (flip_hunter)

Code: `late_entry_v3._evaluate_market()` — side selection block

```python
if underdog_mode:
    entry_side = "NO" if fav_side == "YES" else "YES"
    entry_price = min(yes_ask, no_ask)
else:
    entry_side = fav_side
    entry_price = fav_price
```

Scenarios:
- yes_ask=0.70, no_ask=0.30, underdog_mode=True, fav_price_min=0.26, fav_price_max=0.36:
  - entry_side = "NO" (cheap side) ✓
  - entry_price = 0.30 (within 0.26–0.36) ✓
  - ENTERS with side=NO ✓
- yes_ask=0.75, no_ask=0.20, underdog_mode=True, fav_price_min=0.26:
  - entry_price = 0.20 < 0.26 → REJECTED "fav_price_too_low" ✓
- underdog_mode=False, yes_ask=0.65, no_ask=0.25:
  - entry_side = "YES" (standard majority mode) — NO REGRESSION ✓

Tests:
- `test_flip_hunter_enters_cheap_side` PASS
- `test_flip_hunter_skips_when_cheap_side_outside_range` PASS
- `test_flip_hunter_does_not_affect_standard_mode` PASS (regression)
- `test_enters_favored_yes_side` PASS (existing regression)
- `test_enters_favored_no_side` PASS (existing regression)

### 1C. Router / activation gate

`_PRESET_PARAMS` now includes safe_close and flip_hunter. `_CRYPTO_SHORT_PRESETS` includes both → activating either preset locks category=Crypto and requires timeframe. Verified in code at router.py:641–645, 648.

### 1D. Frontend unlock

STRATEGY_PRESETS contains all 3 candle presets. COMING_SOON_PRESETS is empty. Verified in AutoTradePage.tsx:19–49.

### 1E. Telegram picker

VISIBLE_PRESET_ORDER = ("close_sweep", "safe_close", "flip_hunter") verified in presets.py:224–226.

---

## PHASE 2 — Pipeline End-to-End

Signal path unchanged: `scan()` → `_evaluate_market()` → `SignalCandidate` → `_process_candidate()` → `TradeEngine` → risk gate → paper fill.

New params (`min_entry_sec`, `underdog_mode`) are passed as keyword args through this path. No bypass of any pipeline stage. Risk gate is mandatory inside TradeEngine — unchanged.

`_PRESET_ALLOWED` already maps safe_close → {late_entry_v3} and flip_hunter → {late_entry_v3} (signal_scan_job.py:118–119). No new routing logic required.

Dedup / idempotency: `_process_candidate` dedup logic unchanged.

---

## PHASE 3 — Failure Modes

| Scenario | Behavior |
|---|---|
| `get_crypto_window_markets` fails | `scan()` returns [] (line 184–186), no crash |
| `get_book` fails for one side | `_best_ask` returns None → `empty_book` reject (lines 432–438) |
| min_entry_sec=None for close_sweep | Floor gate skipped, existing behavior preserved |
| underdog_mode=False (default) | Standard majority-side entry, all existing tests pass |
| fav_price outside 0.26–0.36 for flip_hunter | Rejected with `fav_price_too_low` / `fav_price_too_high` |
| config.get_settings() raises | Falls back to `_CANDLE_PRESET_PARAMS` dict (signal_scan_job.py:1463) |
| `_le_pp` is None (full_auto/default preset) | None-guarded: `float(_le_pp["min_ask_diff"]) if _le_pp else None` (line 1311) |

All existing failure mode tests pass (test_market_fetch_error_returns_empty, test_skips_when_book_empty, etc.).

---

## PHASE 4 — Async Safety

No new shared mutable state. All new parameters are passed as immutable kwargs per-call. No threading introduced. `asyncio.gather` usage for book fetches (line 428) unchanged.

No race condition: `_preset_params` dict in `run_close_sweep_fast` is built fresh each tick from config — no module-level mutable state shared between ticks.

HARD RULE: `import threading` — 0 occurrences in modified files. ✓

---

## PHASE 5 — Risk Rules in Code

| Rule | Status |
|---|---|
| Kelly a=0.25 fractional | UNCHANGED — `_SUGGESTED_SIZE_FRACTION=0.04` in late_entry_v3.py:63 |
| Max position ≤10% equity | UNCHANGED — `_MAX_PER_TRADE_PCT=0.10` in late_entry_v3.py:71 |
| Daily loss −$2k hard stop | UNCHANGED — gate.py enforces, no changes |
| Drawdown >8% auto-halt | UNCHANGED — gate.py enforces, no changes |
| Signal dedup | UNCHANGED — `_process_candidate` idempotency key unchanged |
| Kill switch | UNCHANGED — `kill_switch_is_active` check at scan loop entry |
| ENABLE_LIVE_TRADING guard | UNCHANGED — paper mode only; no modification |

All 195 position + exit_watcher tests pass (covers force_close_intent, TP/SL, market_expired).

---

## PHASE 6 — Latency

No new DB queries in the scan hot path. New params are in-memory dict lookups. The `min_entry_sec` check is a float comparison (nanosecond-range). No latency regression.

---

## PHASE 7 — Infra

No migration required. No schema change. Config additions are optional env overrides with defaults. Config keys: `PRESET_SAFE_CLOSE_MIN_ENTRY_SEC=30.0`, `PRESET_FLIP_HUNTER_FAV_PRICE_MAX=0.36`, `PRESET_FLIP_HUNTER_FAV_PRICE_MIN=0.26`.

---

## PHASE 8 — Telegram

Telegram picker now shows 3 presets. Keyboard layout verified: 2 preset rows (close_sweep+safe_close / flip_hunter) + 1 nav row. Tests `test_picker_keyboard_has_two_col_grid_layout` and `test_preset_picker_is_two_col` updated and passing.

---

## Critical Issues

None found.

---

## Stability Score Breakdown

| Category | Weight | Score | Notes |
|---|---|---|---|
| Architecture | 20% | 20 | Clean extension — no refactor of existing signal path |
| Functional | 20% | 18 | 5 new hermetic tests cover min_entry_sec + underdog_mode; existing 30 tests unchanged |
| Failure modes | 20% | 18 | All failure paths handled; None-guards on new params |
| Risk rules | 20% | 20 | No risk gate, sizing, or guard changes |
| Infra + Telegram | 10% | 9 | No migration; picker updated; keyboard tests pass |
| Latency | 10% | 6 | No latency measurement possible without live env; code inspection clean |

**Total: 91/100**

---

## GO-LIVE STATUS: APPROVED

Score 91/100, 0 critical issues.

All 1767 tests pass (1 skip, 24 warnings — pre-existing).

New behaviors proven by hermetic tests:
- safe_close min_entry_sec floor rejects entries inside 30s, enters at 30–60s ✓
- flip_hunter underdog_mode enters cheap side (0.26–0.35), rejects out-of-range ✓
- Standard mode (close_sweep) unaffected — full regression pass ✓

Cleared to merge on CI green.
Post-merge: deploy to Fly and observe scan_summary logs for `underdog=True` + `min_entry_sec=30` entries.

---

## Fix Recommendations

None required — no blockers.

P2 (non-blocking, future lane): flip_hunter currently uses `evaluate_exit` flip-stop (exit when favored price ≤ 0.48), which is less meaningful for the underdog direction. TP/SL and market-expiry paths protect positions adequately in the interim. A dedicated underdog exit strategy (hold until favored price exceeds X, then exit) would improve flip_hunter's edge — defer to a future lane.
