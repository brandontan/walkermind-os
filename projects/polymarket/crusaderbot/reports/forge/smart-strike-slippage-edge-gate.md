# Smart Strike LIVE Slippage-Gate Edge Policy (F1 + F2)

Role: WARP•R00T (audit → fix; risk-stage hardening)
Branch: WARP/smart-strike-slippage-edge-gate
Validation Tier: MAJOR (RISK stage / LIVE-trading gate behavior)
Claim Level: NARROW INTEGRATION (LIVE step-14b slippage path; PAPER unaffected)
Validation Target: (F1) a LIVE Smart Strike (late_entry_v3) candidate is no longer
  auto-HALTed by the step-14b slippage-of-edge tier when it carries no measured
  edge — for a cell with an explicit per-cell $ cap, that cap becomes the sole LIVE
  control (cap-only), default ON via SMART_STRIKE_REQUIRE_MEASURED_EDGE=False, admin-
  flippable to require a measured edge. (F2) 15m candle cells gain per-cell LIVE caps.
Not in Scope: wiring a real measured edge for late_entry_v3 (Option 3 — NEXT task,
  toggle-gated here); slippage TIER thresholds (GREEN/WATCH/HALT unchanged); the
  per-cell cap VALUES for 5m (unchanged); ENABLE_LIVE_TRADING / the 5 validation
  flags / USE_REAL_CLOB / WARP-92 global toggle / kill_switch / Kelly a=0.25 /
  strategy entry-exit logic / migrations.
Suggested Next Step: WARP🔹CMD review + merge. Then Option 3 (real measured edge,
  data-gated) as the follow-up lane the admin toggle switches onto.

---

## 0. Origin — full audit of Smart Strike "no bugs at live" (owner directive)

A read-only WARP•SENTINEL-style audit of the candle_auto → late_entry_v3 LIVE path
found PAPER = safe/working but LIVE = blocked by one critical latent bug (F1), plus a
medium gap (F2). Risk-constant invariants verified intact (Kelly 0.25, max-position
10%, daily −$2k, drawdown 8%, liquidity $10k, complete-set 2% floor). candle_auto =
precedence router (EV orchestrator dormant); market-wide open-position dedup → at most
one position per candle; TP/SL single-source-of-truth; no fabricated fills; async
per-user isolation. The prior `reports/sentinel/smart-strike-live-readiness.md`
(READY-PENDING-OWNER) verified the gate was *wired* but did not trace that the flagship
strategy feeds it a None edge → auto-HALT. Owner picked: F1 → Option 1 (cap-only) now,
admin-toggleable to a future real-edge mode; F2 → add 15m caps.

## 1. What was built

### F1 — cap-only LIVE slippage policy for an unmeasured edge
`late_entry_v3` is a book-imbalance strategy with no measured EV, so
`signal_scan_job._edge_bps_from_metadata` returns None → `GateContext.edge_bps=None`.
The LIVE-only step-14b slippage-of-edge tier fail-closes to HALT on a None edge
(`classify_slippage_tier`: "cannot pay slippage out of zero edge"), so EVERY live Smart
Strike candidate was rejected `slippage_halt` — the per-cell caps (btc/5m $500 …) never
mattered. Paper-invisible (step 14b runs only when `chosen_mode=="live"`).

Fix: `evaluate_slippage_gate` gains `require_measured_edge: bool` (default True =
back-compat). When False (the Smart Strike default) AND the candidate has no measurable
edge AND the cell has an explicit per-cell $ cap AND the slippage estimate is finite →
pass `slippage_cap_only_no_edge` (the per-cell $ cap, enforced in check 1, is the sole
LIVE control). An UNCAPPED cell with no edge still HALTs (fail-closed). A non-finite
slippage estimate still HALTs (data fault). A measured edge → the GREEN/WATCH/HALT tier
is unchanged. When True (admin toggle ON, future real-edge posture) a missing edge HALTs.

The policy is an admin overlay `SMART_STRIKE_REQUIRE_MEASURED_EDGE` (bool, default OFF):
resolved once per candidate in the async orchestrator (`_process_candidate`, 30s-cached,
fail-safe to the env default) and threaded TradeSignal → GateContext →
`evaluate_slippage_gate`. It is NEVER read inside the pure gate (honours the #1694
pool-wedge RCA, same pattern as WARP-89's capital_alloc_pct preload).

### F2 — 15m per-cell LIVE size caps
WARP-95 restored 15m candle scanning, but `LIVE_SIZE_CAPS_USDC` was 5m-only, so a 15m
LIVE entry would have no per-cell $ cap (cap-only F1 then refuses it as uncapped).
Added btc/15m $500, eth/15m $100, sol/15m $100 — MIRRORING the 5m caps as a conservative
initial value (a 15m candle accrues book depth over a 3× longer window, so the 5m cap is
a strict lower bound). Flagged for CMD confirm; re-tune from live-fill data with the 5m caps.

## 2. Current system architecture

DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING (unchanged). RISK gate
step 14b (LIVE-only) now: per-cell $ cap (fail-closed) → if no measured edge:
require_measured_edge ? HALT : (capped+finite-slip ? cap-only pass : HALT) → else the
GREEN/WATCH/HALT slippage-of-edge tier. PAPER path and every other gate step unchanged.

## 3. Files created / modified (full repo-root paths)

Created:
- projects/polymarket/crusaderbot/reports/forge/smart-strike-slippage-edge-gate.md (this report)

Modified:
- projects/polymarket/crusaderbot/domain/risk/slippage_gate.py — `require_measured_edge` param + cap-only branch; 15m caps (F2)
- projects/polymarket/crusaderbot/domain/risk/gate.py — GateContext.require_measured_edge; pass it to evaluate_slippage_gate; log the actual pass reason
- projects/polymarket/crusaderbot/services/trade_engine/engine.py — TradeSignal.require_measured_edge + _build_gate_context threading
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py — resolve SMART_STRIKE_REQUIRE_MEASURED_EDGE in _process_candidate; thread to _build_trade_signal → TradeSignal
- projects/polymarket/crusaderbot/config.py — SMART_STRIKE_REQUIRE_MEASURED_EDGE env default (False)
- projects/polymarket/crusaderbot/domain/ops/runtime_config.py — SMART_STRIKE_REQUIRE_MEASURED_EDGE admin overlay (bool)
- projects/polymarket/crusaderbot/tests/test_slippage_gate.py — 15m locked values; 6 cap-only/require-edge tests; uncapped-cell cases re-keyed off sol/15m
- projects/polymarket/crusaderbot/tests/test_smart_strike_cell_cap_binding.py — 15m cap binds; require_measured_edge threading + default; sol/15m → doge/5m
- projects/polymarket/crusaderbot/tests/test_robustness_gate.py — _signal_ns mock gains require_measured_edge

## 4. What is working

- test_slippage_gate.py + test_smart_strike_cell_cap_binding.py: 35 pass (cap-only passes a
  capped no-edge cell; still enforces the $ cap; HALTs an uncapped no-edge cell; HALTs on
  non-finite slip; require_measured_edge=True HALTs; measured-edge tiers unchanged; 15m caps bind).
- Regression: test_signal_scan_job / test_robustness_gate / test_fast_track_a /
  test_admin_console / test_auto_risk_profile / test_gate_capital_alloc_preload all green (257).
- Full crusaderbot suite: 3201 passed, 15 skipped; the only 4 failures (test_clob_pysdk
  error-mapping) are pre-existing + unrelated — git-stash confirmed they fail identically
  on the base (ModuleNotFoundError, optional py-clob-client not installed). ruff clean.

## 5. Known issues / notes

- Default (cap-only) means LIVE Smart Strike trades bounded by the per-cell $ cap + the
  global brakes (Kelly 0.25, ≤10% position, daily −$2k, drawdown 8%, exposure, kill switch)
  but with NO slippage-of-edge tier check (no measured edge to ratio against). This is the
  accepted posture until the real-edge lane (Option 3) lands; flip the admin toggle ON to
  require a measured edge then.
- 15m cap values mirror 5m (conservative) — pending CMD confirm + live-fill tuning.
- This lane does not give late_entry_v3 a real edge; Option 3 is the data-gated follow-up.

## 6. What is next

- WARP🔹CMD review + merge (MAJOR, LIVE risk path).
- Option 3 (NEXT task): wire a real measured edge for late_entry_v3 (e.g. oracle
  fair-value edge when ORACLE_ENABLED) so the slippage-of-edge tier has an honest
  denominator; the admin toggle SMART_STRIKE_REQUIRE_MEASURED_EDGE then enforces it.
- Pre-go-live: confirm 15m cap values; re-tune all caps after the first LIVE week.
