# Smart Strike Option 3 — real measured edge for the LIVE slippage tier

Role: WARP•R00T (follow-up lane to smart-strike-slippage-edge-gate F1)
Branch: WARP/smart-strike-real-edge
Validation Tier: MAJOR (RISK stage / LIVE-trading gate behavior)
Claim Level: NARROW INTEGRATION (LIVE step-14b only; PAPER unaffected)
Validation Target: late_entry_v3 now supplies a REAL measured per-trade gross edge
  (the entry-side oracle fair-value edge) so the step-14b slippage-of-edge tier has an
  honest denominator. Consumed ONLY in real-edge mode (SMART_STRIKE_REQUIRE_MEASURED_EDGE
  ON); the cap-only default (F1) is unchanged.
Not in Scope: changing the cap-only default; the slippage TIER thresholds; the
  directional MIN_EDGE_BPS step-12 floor (deliberately NOT fed — late_entry stays
  ungated there); enabling the oracle (operator/Fly: ORACLE_ENABLED + ORACLE_EDGE_GATE_
  ENABLED); ENABLE_LIVE_TRADING / guards / Kelly / migrations.
Suggested Next Step: WARP🔹CMD review + merge. Operator (to use real-edge mode): enable
  the oracle, then flip SMART_STRIKE_REQUIRE_MEASURED_EDGE ON via admin.

---

## 1. What was built

Owner directive: prepare Option 3 (a real measured edge for late_entry_v3) as the
admin-toggleable real-edge mode behind the F1 default. late_entry_v3 already computes an
ADVISORY oracle fair-value edge per candle (`compute_edge`: edge_up = fair_up − ask_up,
edge_down = (1−fair_up) − ask_down). Option 3 promotes that into the slippage gate's
gross-edge denominator for the ENTERED side, without disturbing anything else.

1. **Strategy stamp** (`domain/strategy/strategies/late_entry_v3.py`): when the oracle
   status is `computed`, stamp `metadata["slippage_gross_edge_bps"]` = the entry side's
   oracle edge × 10_000 (edge_up for a YES entry, edge_down for NO), ONLY when that edge
   is finite and **> 0**. Absent otherwise (oracle off / warming / non-positive edge).
   Deliberately a SEPARATE key from `edge`/`edge_bps`, so `_edge_bps_from_metadata` and
   the directional step-12 MIN_EDGE_BPS floor are unchanged for late_entry (no paper
   behavior change).

2. **Threading**: `signal_scan_job._build_trade_signal` reads it (None-safe) →
   `TradeSignal.slippage_gross_edge_bps` → `engine._build_gate_context` →
   `GateContext.slippage_gross_edge_bps` (all optional/defaulted None, byte-compatible).

3. **Gate consumption** (`domain/risk/gate.py` step 14b): the slippage gross-edge
   denominator is selected as `ctx.slippage_gross_edge_bps` **only when
   `ctx.require_measured_edge` is True** (real-edge mode); otherwise it stays
   `ctx.edge_bps` (None for late_entry → cap-only F1). So the toggle is the clean mode
   selector — OFF = cap-only (ignore the measured edge), ON = real-edge tier. Other
   strategies keep `ctx.edge_bps` either way (unaffected).

## 2. Behavior matrix (LIVE step 14b; PAPER unaffected — step 14b is LIVE-only)

- Toggle OFF (default, F1): capped Smart Strike cell, edge ignored → cap-only pass
  (`slippage_cap_only_no_edge`); uncapped → HALT.
- Toggle ON + oracle gives a positive entry-side edge → GREEN/WATCH/HALT by
  `slippage_bps / oracle_edge_bps` (the real-edge tier).
- Toggle ON + no oracle edge (oracle off/warming, or edge ≤ 0) → HALT (`slippage_halt`)
  — "require a measured edge, none available, don't trade."

## 3. Files created / modified (full repo-root paths)

Created:
- projects/polymarket/crusaderbot/tests/test_smart_strike_real_edge.py (4 stamping tests)
- projects/polymarket/crusaderbot/reports/forge/smart-strike-real-edge.md (this report)

Modified:
- projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py — stamp slippage_gross_edge_bps (entry-side oracle edge, positive only); +import math
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py — read metadata → TradeSignal.slippage_gross_edge_bps
- projects/polymarket/crusaderbot/services/trade_engine/engine.py — TradeSignal field + _build_gate_context threading
- projects/polymarket/crusaderbot/domain/risk/gate.py — GateContext field + step-14b gross-edge selection (real-edge mode only)
- projects/polymarket/crusaderbot/tests/test_smart_strike_cell_cap_binding.py — slippage_gross_edge_bps threading + default tests; _signal_ns field
- projects/polymarket/crusaderbot/tests/test_robustness_gate.py — _signal_ns field

## 4. What is working

- test_smart_strike_real_edge.py (4): stamps the entry-side edge for favored YES (==
  oracle_edge_up×10_000) and NO (== oracle_edge_down×10_000); no oracle → no stamp;
  non-positive entry-side edge → no stamp.
- Threading + defaults: test_smart_strike_cell_cap_binding (TradeSignal → GateContext;
  TradeSignal default None). late_entry_v3 / robustness / slippage / signal_scan /
  fast_track / auto_risk / warp54 / complete_set regression green.
- Full suite 3207 passed (4 pre-existing-unrelated clob_pysdk fails, git-stash
  confirmed), ruff clean.

## 5. Known issues / notes

- Real-edge mode only does anything when the oracle is enabled (ORACLE_ENABLED +
  ORACLE_EDGE_GATE_ENABLED) — otherwise no edge is stamped and the toggle ON simply
  HALTs. The readiness audit flagged verifying the RTDS feed before relying on it live.
- For candle markets near 0.50 the oracle edge can be small; in real-edge mode a trade
  whose slippage exceeds 30% of that edge HALTs — intended risk management, but expect
  more HALTs than cap-only. Tune via the slippage tiers / per-cell caps if needed.
- The oracle edge is a single-read fair-value estimate (not a proven realized EV — WARP-58
  late_entry edge is statistically unproven); it is used as the slippage denominator, NOT
  promoted to the directional step-12 floor.

## 6. What is next

- WARP🔹CMD review + merge.
- Operator: enable the oracle + flip SMART_STRIKE_REQUIRE_MEASURED_EDGE ON to run real-edge mode.
- Optional data lane: log/compare cap-only vs real-edge HALT rates on paper accrual before any live cutover to real-edge mode.
