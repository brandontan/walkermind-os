# Forge Report — WARP/R00T/complete-set-edge-metric

**Date:** 2026-05-30 16:11 Asia/Jakarta
**Role:** WARP•R00T
**Branch:** WARP/R00T/complete-set-edge-metric
**Lane:** 3 of 5 (Polybot directive — defensive guardrails campaign)
**Validation Tier:** MINOR
**Claim Level:** FOUNDATION
**Validation Target:** late_entry_v3 candidate metadata gains `complete_set_edge` field
**Not in Scope:** trade logic / risk gate / entry filters; operator dashboard wiring; promotion to hard gate
**Suggested Next:** WARP🔹CMD review → merge → proceed to Lane 4 (`WARP/R00T/safe-close-direction-limit`)

---

## 1. What was changed

`late_entry_v3._evaluate_market` now computes the textbook complete-set arbitrage edge as `edge = round(1.0 - (yes_ask + no_ask), 4)` and stamps it into every candidate's metadata as `complete_set_edge`.

Polymarket binary UP/DOWN markets settle to $1.00 at expiry, so:
- `edge > 0` → cost < 1.00 → textbook taker-side arbitrage exists at quoted TOB (rare; book depth usually kills the actual fill).
- `edge = 0` → cost = 1.00 → efficient pricing.
- `edge < 0` → cost > 1.00 → market overpriced relative to settlement bound (taker can never profit from full both-leg buy).

**FOUNDATION lane — no trade-logic change.** The metric is observational only. Operator dashboards / aggregate alerts / future hard-gate lanes can read the field once data shows whether the signal is predictive.

The data was already implicitly available via the existing `spread = yes_ask + no_ask` field, but consumers had to recompute `1 - spread` themselves. Explicit naming + rounding eliminates that duplication and matches the Polybot directive vocabulary.

---

## 2. Files modified (full repo-root paths)

| Action | File | Lines | Purpose |
|---|---|---|---|
| Modified | `projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py` | +18 | Compute `complete_set_edge`; stamp in SignalCandidate metadata between existing `spread` and `seconds_to_close` keys |
| Created | `projects/polymarket/crusaderbot/tests/test_complete_set_edge_metric.py` | +199 | 9 hermetic tests — source pins, parametrized math fingerprint, behavioural edge cases (zero / negative / positive regimes) |
| Created | `projects/polymarket/crusaderbot/reports/forge/complete-set-edge-metric.md` | this report | WARP•R00T evidence trail |

---

## 3. Validation declaration

```
Validation Tier   : MINOR
Claim Level       : FOUNDATION
Validation Target : late_entry_v3._evaluate_market complete_set_edge computation + metadata stamp
Not in Scope      : trade logic / gates / dashboards; promotion to hard arb gate
Suggested Next    : WARP🔹CMD review
```

**Verified locally:** py_compile clean on the 1 modified production file; 9/9 new tests pass; full Lane 1+2+3 + neighbor regression 185/185 pass (test_complete_set_edge_metric + test_close_sweep_spread_gate + test_tob_freshness_gate + test_late_entry_v3 + test_signal_scan_job + test_flip_hunter_stale_price_fix).

**Lane plan:**

| # | Lane | Tier | Status |
|---|---|---|---|
| 1 | `WARP/R00T/tob-freshness-gate` | MAJOR-NARROW | ✅ MERGED #1475 + DEPLOYED |
| 2 | `WARP/R00T/close-sweep-spread-gate` | STANDARD-NARROW | ✅ MERGED #1476 + DEPLOYED |
| 3 | `WARP/R00T/complete-set-edge-metric` | MINOR-FOUNDATION | **THIS PR** — pending review |
| 4 | `WARP/R00T/safe-close-direction-limit` | STANDARD-NARROW | queued |
| 5 | `WARP/R00T/bankroll-dynamic-sizing` | MAJOR-NARROW | queued |
