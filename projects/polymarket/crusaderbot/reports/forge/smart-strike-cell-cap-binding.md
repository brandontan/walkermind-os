# WARP•FORGE — smart-strike-cell-cap-binding (WARP-87 follow-up, GAP B)

Branch: WARP/smart-strike-cell-cap-binding
Validation Tier: MAJOR (LIVE-trading RISK path — execution / capital safety)
Claim Level: NARROW INTEGRATION (cell/depth/spread now flow candidate → GateContext; the LIVE-only step-14b consumer binds on them; no LIVE runtime exercised — system is PAPER)
Validation Target: the candidate → TradeSignal → GateContext threading of `cell` / `orderbook_depth_usdc` / `spread`, and the per-cell LIVE size cap binding (btc/5m $500, eth/5m $100, sol/5m $100) at `gate.evaluate` step 14b.
Not in Scope: any LIVE flip; the slippage TIER thresholds (GREEN ≤15% / WATCH 15-30% / HALT >30%); the btc/eth cap values; the WARP-78 EV-cutover compose (separate lane); fast_topup (non-Smart-Strike, intentionally left None); migrations; strategy entry/exit logic.

---

## 1. What was built

Closed GAP B — the WARP-87 follow-up that never landed. WARP-87 added the
per-cell LIVE size caps + tiered slippage gate (`domain/risk/slippage_gate.py`)
consumed by `domain/risk/gate.py` step 14b via `ctx.cell` /
`ctx.orderbook_depth_usdc` / `ctx.spread`, and added those three optional fields
to `GateContext`. But the TradeEngine path never populated them, so on real flow
`ctx.cell` was always `None` → the per-cell caps silently never fired and the
slippage estimate ran on the `market_liquidity` / `1.0` fallback inputs.

This lane threads the Smart Strike candidate's already-measured values
end-to-end and adds the CMD-approved `sol/5m` cap:

1. `late_entry_v3` stamps `cell` (canonical `"{ASSET}/{timeframe}"`) +
   `orderbook_depth_usdc` (the CLOB book depth, = `clob_liquidity`) onto the
   surviving candidate's metadata, next to the existing `spread` / `clob_liquidity`.
   Metadata-only — no entry/exit logic change.
2. `signal_scan_job._build_trade_signal` reads `cell` / `orderbook_depth_usdc` /
   `spread` off `cand.metadata` (None-safe) into the `TradeSignal`.
3. `TradeSignal` gains optional/defaulted `cell` / `orderbook_depth_usdc` /
   `spread` (byte-compatible, same WARP-87/89 threaded-field pattern);
   `TradeEngine._build_gate_context` passes them straight into `GateContext`.
4. `slippage_gate.LIVE_SIZE_CAPS_USDC` adds `sol/5m = 100.0` (conservative
   initial cap pending live-fill observation — FLAGGED for CMD confirm).

`gate.evaluate` step 14b already consumes `ctx.cell` (passed verbatim into
`evaluate_slippage_gate`) and already estimates slippage from
`ctx.orderbook_depth_usdc` / `ctx.spread` when present (else the existing
fallback). So with the fields now populated, the caps bind on real flow with no
change to the gate consumer itself.

---

## 2. Current system architecture

Pipeline position (CLAUDE.md LOCKED): DATA → STRATEGY → INTELLIGENCE → RISK →
EXECUTION → MONITORING. All change is in STRATEGY (metadata stamp, no logic) and
the RISK-stage feed.

The closed path:

```
late_entry_v3._evaluate_market
    SignalCandidate.metadata{ cell, orderbook_depth_usdc, spread, clob_liquidity, ... }
        │  (cell = normalize_cell_key(asset, timeframe), fail-soft → None)
        ▼
signal_scan_job._build_trade_signal
    reads cand.metadata → TradeSignal.cell / .orderbook_depth_usdc / .spread   (None-safe)
        ▼
TradeEngine._build_gate_context
    GateContext.cell / .orderbook_depth_usdc / .spread = signal.*
        ▼
gate.evaluate  (chosen_mode == 'live'  → step 14b, LIVE-only)
    _depth  = ctx.orderbook_depth_usdc  if not None else ctx.market_liquidity
    _spread = ctx.spread                if not None else 1.0
    estimate_slippage_bps(stake, _depth, _spread, entry_price)
    evaluate_slippage_gate(cell=ctx.cell, proposed_size_usdc=final_size, ...)
        per-cell LIVE size cap (btc/5m $500 · eth/5m $100 · sol/5m $100)
        then GREEN / WATCH / HALT tier verdict
```

None-safety: a non-Smart-Strike / fast_topup candidate omits the metadata keys →
`TradeSignal.*` default to `None` → `GateContext.*` `None` → the gate keeps its
existing `market_liquidity` / `1.0` fallback and applies no per-cell cap. No
regression. Paper path is untouched (step 14b runs only for `chosen_mode=='live'`).

---

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py` — stamp `cell` (via local `normalize_cell_key`, fail-soft → None) + `orderbook_depth_usdc` (= `clob_liquidity`) into the candidate metadata. No entry/exit logic change.
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — `_build_trade_signal` reads `cell` / `orderbook_depth_usdc` / `spread` off `cand.metadata` (None-safe) and passes them to `TradeSignal`.
- `projects/polymarket/crusaderbot/services/trade_engine/engine.py` — `TradeSignal` gains optional/defaulted `cell` / `orderbook_depth_usdc` / `spread`; `_build_gate_context` threads them into `GateContext`.
- `projects/polymarket/crusaderbot/domain/risk/slippage_gate.py` — `LIVE_SIZE_CAPS_USDC` adds `sol/5m: 100.0` + docstring/comment note (conservative, pending live-fill, CMD confirm).
- `projects/polymarket/crusaderbot/tests/test_slippage_gate.py` — `test_live_size_caps_locked_values` now asserts the 3-cell dict incl. `sol/5m`.
- `projects/polymarket/crusaderbot/tests/test_robustness_gate.py` — `_signal_ns` mock gains `cell` / `orderbook_depth_usdc` / `spread` = `None` (so `_build_gate_context` reads them).
- `projects/polymarket/crusaderbot/tests/test_signal_scan_job.py` — 2 new tests: `_build_trade_signal` threads cell/depth/spread from metadata; None when metadata absent.

Created:
- `projects/polymarket/crusaderbot/tests/test_smart_strike_cell_cap_binding.py` — TradeSignal→GateContext threading; TradeSignal defaults None; per-cell cap binds for btc/eth/sol (above-cap → `slippage_live_size_cap` reject, at/under-cap pass); case-insensitive cell; None-cell → no cap; out-of-set cell → no cap.

---

## 4. What is working

- `pytest projects/polymarket/crusaderbot/tests/ -q` → **3160 passed, 15 skipped**, plus the **4 known pre-existing-unrelated `test_clob_pysdk.py` failures** (missing optional `polymarket` module — verified present on a clean `origin/main` tree via `git stash`, unrelated to this change).
- `ruff check .` → **All checks passed!**
- Threading proof: `TradeSignal(cell='btc/5m', orderbook_depth_usdc=12345.0, spread=0.97)` → `_build_gate_context` → `GateContext.cell=='btc/5m'`, depth + spread threaded (test_smart_strike_cell_cap_binding).
- Per-cell cap binds (the exact call `gate.evaluate` makes with `ctx.cell`, GREEN slippage isolating the size cap):
  - btc/5m: $500.01 → `rejected`, reason `slippage_live_size_cap`; $500.00 → passes.
  - eth/5m: $150 → reject; $80 → pass.
  - sol/5m: $150 → reject; $100.00 → passes (new cell).
  - case-insensitive: `'BTC/5m'` $600 → reject (gate normalises before lookup).
- None-safety: `cell=None`, size $1,000,000 → `size_cap_usdc is None`, not rejected (tier still applies); legacy candidates unaffected.

---

## 5. Known issues

- **sol/5m = $100 is a conservative initial cap** pending live-fill observation — FLAGGED for final CMD confirm before the sol/5m cell is allowed LIVE. btc/5m $500 + eth/5m $100 are the owner-locked WARP-87 values (unchanged).
- `orderbook_depth_usdc` deliberately reuses `clob_liquidity` (the CLOB book-depth source per the WARP-71 audit) rather than a separate book-depth read — consistent with how the gate's fallback already treats `market_liquidity` as depth. No new market read added.
- The FactorVector `factor_*` shadow metadata is gated by `_factor_vector_enabled()` and was NOT relied on for `cell` — `cell`/`orderbook_depth_usdc` are stamped unconditionally on the candidate so the cap binds even with the shadow disabled.
- fast_topup path intentionally not threaded (reactive top-up, not a Smart Strike candidate; no `cand` object) → carries `None` → gate fallback. By design, not a gap.
- This lane does NOT compose the slippage gate with the WARP-78 EV-cutover gate (still the single 50% backstop elsewhere) — separate lane.

---

## 6. What is next

- **WARP•SENTINEL** validation (MAJOR — LIVE RISK path). Verify (a) the threading path; (b) the per-cell cap binds for btc/eth/sol at step 14b under `chosen_mode='live'`; (c) None-safety / no paper regression; (d) the listed invariants untouched.
- CMD: confirm `sol/5m = $100` (or set the LIVE v1 value) before the sol/5m cell goes LIVE.
- Future lane: compose the slippage gate with the WARP-78 EV-cutover gate (replace the single 50% backstop).

Suggested Next Step: hand to WARP•SENTINEL on this branch; on APPROVED, CMD confirms the sol/5m cap value and decides merge.
