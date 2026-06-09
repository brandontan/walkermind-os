# Forge Report — WARP/R00T/close-sweep-spread-gate

**Date:** 2026-05-30 15:23 Asia/Jakarta
**Role:** WARP•R00T
**Branch:** WARP/R00T/close-sweep-spread-gate
**Lane:** 2 of 5 (Polybot directive — defensive guardrails campaign)
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** late_entry_v3 close_sweep candidate path — entry rejection when per-leg bid-ask spread exceeds threshold
**Not in Scope:** safe_close / flip_hunter (no-op via `max_leg_spread=None`); complete-set edge gate (Lane 3); risk gate; sizing
**Suggested Next:** WARP🔹CMD review → merge → proceed to Lane 3 (`WARP/R00T/complete-set-edge-metric`)

---

## 1. What was built

Per-leg bid-ask spread guard for the `close_sweep` preset. In the noisy final ~35s before candle close, book depth thins and a wide per-side spread = high slippage on a taker fill. When either leg's `(best_ask - best_bid)` exceeds `config.CLOSE_SWEEP_MAX_LEG_SPREAD` (default 0.02 / 2c), the candidate is rejected with `reject_reason="leg_spread_too_wide"`.

**Scope discipline:**
- `safe_close` + `flip_hunter` enter earlier in the candle window where this is not the dominant risk — those presets omit the `max_leg_spread` key from `_resolve_preset_params`, the call site passes `None`, and the gate no-ops.
- The existing complete-set `spread = yes_ask + no_ask` vs `MAX_SPREAD=1.05` check stays intact and applies to all three presets. The new gate is additive, not a replacement.

**No change to:** complete-set check, ask-diff filter, timing gates, sizing path, risk gate, force-exit timing, paper-default invariant, activation guards. Lane 1 (TOB freshness gate) is unaffected — both gates compose cleanly in `_evaluate_market` / `_process_candidate`.

**Operator escape hatch:** `CLOSE_SWEEP_MAX_LEG_SPREAD=0` disables the gate without redeploy (runtime branches on `> 0`). Negative values rejected at config load with a clear `ValueError` (same trap as `TOB_STALE_MS`).

---

## 2. Current system architecture (relevant slice)

```
late_entry_v3._evaluate_market(..., max_leg_spread)
    └─ pm.get_book(yes_token) + pm.get_book(no_token)   [unchanged — single round trip per leg]
    └─ NEW: _best_bid(yes_book), _best_bid(no_book)     [zero extra network — same /book payload]
    └─ NEW: if max_leg_spread > 0:
        ├─ either bid missing  → reject "leg_spread_missing_bid"
        └─ either (ask - bid)  → reject "leg_spread_too_wide"
                  > threshold
    └─ existing ask_diff / spread / fav_price / timing gates
    └─ stamp metadata: yes_bid, no_bid, leg_spread_yes, leg_spread_no

services.signal_scan.signal_scan_job._resolve_preset_params
    └─ close_sweep dict gains: "max_leg_spread": cfg.CLOSE_SWEEP_MAX_LEG_SPREAD
        (via getattr defensive read — partial-mock cfg objects in tests safe)
    └─ safe_close + flip_hunter dicts OMIT the key → call site passes None → no-op

services.signal_scan.signal_scan_job
    └─ run_close_sweep_fast       → forwards max_leg_spread from pp dict to scan()
    └─ run_once (Phase B2 candle) → same forwarding pattern
```

Pipeline boundary preserved: DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION. The new gate sits in STRATEGY layer alongside ask_diff / spread / fav_price gates — before any risk or execution call.

---

## 3. Files created / modified (full repo-root paths)

| Action | File | Lines | Purpose |
|---|---|---|---|
| Modified | `projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py` | +57 | `_best_bid` helper, `max_leg_spread` param on `scan` + `_evaluate_market`, per-leg gate, metadata stamps |
| Modified | `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` | +14 | `_resolve_preset_params` close_sweep gains `max_leg_spread`; two scan call sites (fast loop + run_once) forward it |
| Modified | `projects/polymarket/crusaderbot/config.py` | +27 | `CLOSE_SWEEP_MAX_LEG_SPREAD: float = 0.02` knob + non-negative `field_validator` |
| Created | `projects/polymarket/crusaderbot/tests/test_close_sweep_spread_gate.py` | +294 | 16 hermetic tests — `_best_bid` correctness, source pins, config knob, behavioural |
| Created | `projects/polymarket/crusaderbot/reports/forge/close-sweep-spread-gate.md` | this report | WARP•R00T evidence trail |

---

## 4. What is working

**Verified locally:**
- `python -m py_compile` clean on all 3 modified production files.
- `pytest projects/polymarket/crusaderbot/tests/test_close_sweep_spread_gate.py` — **16/16 pass** (0.68s).
- Lane 1 + Lane 2 + neighbor regression — `test_close_sweep_spread_gate` + `test_tob_freshness_gate` + `test_late_entry_v3` + `test_signal_scan_job` + `test_flip_hunter_stale_price_fix` + `test_config_defaults` — **176/176 pass** (2.77s).
- Hermetic test coverage:
  - `_best_bid` correctness: highest positive bid, empty / None / malformed handled.
  - Source pin: `_evaluate_market` signature carries `max_leg_spread`.
  - Source pin: gate body contains `leg_spread_too_wide` + short-circuits on `> 0`.
  - Source pin: `_resolve_preset_params` wires close_sweep to `CLOSE_SWEEP_MAX_LEG_SPREAD`.
  - Source pin: both scan call sites forward `max_leg_spread`.
  - Config knob: default 0.02, env override, negative rejection at load.
  - Behavioural: YES leg too wide → reject; NO leg too wide → reject; both tight → accept (with metadata stamps); `max_leg_spread=None` → no-op; `max_leg_spread=0` → no-op; bid missing → reject `leg_spread_missing_bid`.

**Behaviour in production (expected):**
- close_sweep candidates fired in the noisy final 35s: previously could execute on wide-spread books (slippage tax invisible). Now skipped; surfaced in `reject_reason="leg_spread_too_wide"` in scan summary logs.
- safe_close + flip_hunter: zero behavioural change (gate no-ops). Validates PR #1415 Kreo-parity work is untouched.
- `getattr` default = 0.02: even if a deploy ships before the env knob is set, the production default applies — no surprise disable.

---

## 5. Known issues

- **Metadata bloat.** Stamping `yes_bid`, `no_bid`, `leg_spread_yes`, `leg_spread_no` adds 4 fields per candidate. Negligible (~32 bytes), but flagged for future observability cleanup.
- **No integration test through `_process_candidate`.** Lane 1 has runtime integration tests through `_process_candidate`. Lane 2's behavioural tests stop at `_evaluate_market` boundary because the spread gate fires inside the strategy, not in `_process_candidate`. Test coverage via `scan()` would add value but pulls in the full `is_short_crypto_market` eligibility surface — disproportionate for a STANDARD lane. Source pins on the scan call sites + `_resolve_preset_params` cover the wiring; the gate itself is behaviourally tested in isolation.
- **Polymarket /book bid presence assumption.** The gate rejects when a bid is missing (`leg_spread_missing_bid`). This is the safer default in the close_sweep window: no bid = no buyer = even worse fill scenario if we hit a market order. Could be relaxed to "fall through to a smaller threshold" if production data shows legitimate missing bids on otherwise-tradeable books.

---

## 6. What is next

Per WARP🔹CMD-approved 5-lane plan:

| # | Lane | Tier | Status |
|---|---|---|---|
| 1 | `WARP/R00T/tob-freshness-gate` | MAJOR-NARROW | ✅ MERGED #1475 + DEPLOYED |
| 2 | `WARP/R00T/close-sweep-spread-gate` | STANDARD-NARROW | **THIS PR** — pending review |
| 3 | `WARP/R00T/complete-set-edge-metric` | MINOR-FOUNDATION | queued |
| 4 | `WARP/R00T/safe-close-direction-limit` | STANDARD-NARROW | queued |
| 5 | `WARP/R00T/bankroll-dynamic-sizing` | MAJOR-NARROW | queued |

---

## Validation declaration

```
Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : _evaluate_market max_leg_spread gate + _resolve_preset_params close_sweep wiring + both scan call sites + CLOSE_SWEEP_MAX_LEG_SPREAD config knob
Not in Scope      : safe_close / flip_hunter (no-op); complete-set edge gate (Lane 3); risk gate; sizing
Suggested Next    : WARP🔹CMD review
```
