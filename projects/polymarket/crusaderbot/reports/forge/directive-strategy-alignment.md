# Forge Report — directive-strategy-alignment

**Date:** 2026-05-31 18:54 WIB
**Branch:** claude/fervent-thompson-CsdE5
**Role:** WARP•R00T
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Close Sweep, Safe Close, Flip Hunter strategy alignment vs CRUSADERBOT_IMPROVEMENT_DIRECTIVES.md
**Not in Scope:** Execution-layer order management (LIMIT/cancel-replace/auto-cancel), dual-leg simultaneous entry, Safe Close MAKER-edge semantics, Bankroll Service, inventory unit normalization (USDC vs shares)

---

## 1. What was built

Aligned three CrusaderBot strategies with the uploaded CRUSADERBOT_IMPROVEMENT_DIRECTIVES.md.

**Changes implemented:**

### Flip Hunter — Mode A (Pure Arb) alignment
- `underdog_mode`: `False` (Kreo "With Trend") → `True` (Directive Mode A: enter cheap side)
- `fav_price_min/max`: 0.50/0.95 → 0.10/0.36 (cheap_side_min=0.10, cheap_side_max=0.35 exclusive)
- `min_ask_diff`: 0.03 (Kreo 3%) → 0.01 (Directive min_arb_edge=1%)
- Entry window: rem 160–300s (elapsed 0–140s) → rem 60–180s before close per directive
- `force_exit_at_rem_sec`: 160.0/480.0 → 0.0 (Mode A: hold to settlement, no time-based exit)
- Applies to both 5m and 15m timeframes

### Close Sweep — time-based sizing (Directive 1.4)
- Added `size_time_decay: bool = False` parameter to `_evaluate_market()` and `scan()`
- When `size_time_decay=True`: `seconds_left < 10s → 0.5x`, `10–35s → 0.75x` (clamped to $1 min)
- `_CANDLE_PRESET_STATIC["close_sweep"]` now includes `"size_time_decay": True`
- `signal_scan_job.py` passes `size_time_decay=True` to scan() for close_sweep

---

## 2. Current system architecture

```
signal_scan_job.py
  → _resolve_preset_params("flip_hunter", tf)
      → config: PRESET_FLIP_HUNTER_* (Mode A values)
      → underdog_mode=True, fav_price_min=0.10, fav_price_max=0.36, force_exit=0.0
  → late_entry_v3.scan(..., underdog_mode=True, size_time_decay=True/False)
      → _evaluate_market() per market
          → entry_side = cheap side (when underdog=True)
          → entry_price = min(yes_ask, no_ask)
          → price gate: 0.10 <= entry_price < 0.36
          → size_time_decay: apply 0.5x/0.75x multiplier for close_sweep
  → SignalCandidate → _process_candidate → TradeEngine
```

---

## 3. Files created / modified

| Action | File |
|--------|------|
| Modified | `projects/polymarket/crusaderbot/config.py` |
| Modified | `projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py` |
| Modified | `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` |
| Modified | `projects/polymarket/crusaderbot/tests/test_late_entry_v3.py` |
| Created | `projects/polymarket/crusaderbot/reports/forge/directive-strategy-alignment.md` |

---

## 4. What is working

- All 209 existing tests pass (51 late_entry_v3 + 86 flip_hunter/close_sweep + 72 safe_close/inventory)
- Flip Hunter now enters cheap side (0.10–0.35) with underdog_mode=True
- Close Sweep time-based sizing: 0.5x below 10s, 0.75x at 10–35s
- force_exit=0.0 for flip_hunter: positions hold to settlement (no pre-expiry force-close)
- Existing safe_close, complete_set_edge_gate, inventory_tracker remain unchanged

---

## 5. Known issues / gaps (audit findings — not in scope for this PR)

| Gap | Risk | Files |
|-----|------|-------|
| Safe Close uses TAKER edge (ask+ask) not MAKER edge (bid+bid) per directive | LOW — conservative gate | `signal_scan_job.py:2116-2188` |
| Imbalance threshold: 5.0 USDC cost basis vs directive's 20 shares | LOW — directionally same | `config.py` SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC |
| Safe Close LIMIT order management (cancel/replace, min_replace_ms=5000) | MEDIUM — execution layer | TradeEngine (out of scope) |
| Safe Close auto-cancel unfilled if < 20s remaining | MEDIUM — execution layer | TradeEngine / exit_watcher |
| Simultaneous dual-leg TAKER for close_sweep (currently sequential fast-topup) | MEDIUM — execution layer | `signal_scan_job.py:892-1174` |
| Direction WARNING log level (INFO not WARNING) | LOW | `signal_scan_job.py:3308` |
| Inventory logging per candidate (imbalance not in scan metadata) | LOW | `signal_scan_job.py` scan path |
| Flip Hunter < 90s taker conversion if unfilled | LOW — paper mode masks | Execution layer |

---

## 6. What is next

1. WARP🔹CMD review and merge decision
2. Deploy to paper — verify flip_hunter cheap-side entries appear in logs at 60–180s before close
3. Monitor: are entries in 0.10–0.35 price range? Are fast_topups completing the expensive leg?
4. Execution-layer order management (MEDIUM gaps above) — separate WARP•FORGE lane
5. Imbalance unit normalization (USDC → shares) if WARP🔹CMD decides to align with directive exactly

---

**Suggested Next Step:** WARP🔹CMD review — merge to main + deploy to paper to observe Mode A behavior.
