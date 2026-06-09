# WARP-87 — Sub-Lane C Slippage Gate Wire-up

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: the tiered LIVE-cutover slippage gate (GREEN/WATCH/HALT) +
per-cell LIVE size caps, wired into `domain/risk/gate.py:evaluate` for the
LIVE-routed path only, with a pure (no-DB) per-candidate hot path.
Not in Scope: populating `GateContext.cell` / `orderbook_depth_usdc` / `spread`
at the candidate construction sites (engine.py, scheduler.py, complete_set_scan.py,
parity.py) — that is the proposal's documented follow-up lane and is OUTSIDE the
D1 scope lock (`domain/risk/` + tests only); the WARP-78 EV cutover gate (this is
the slippage layer that composes with it); any sizing-constant or strategy change.
Suggested Next Step: WARP🔹CMD review (owner already picked the tiers + caps in
this directive; the follow-up lane threads cell/depth/spread into GateContext at
the candidate sources so the per-cell caps and tier gate fire on real LIVE data).

---

## 1. What was built

The locked Sub-Lane C threshold proposal (`reports/forge/cutover-slippage-thresholds.md`,
PR #1691) is now CODE in the RISK stage — not a report. Two pieces:

1. **New pure module `domain/risk/slippage_gate.py`** — the tiered slippage-of-edge
   classifier + per-cell LIVE size caps, all owner-locked:
   - Tiers (slippage bps ÷ gross edge bps): `GREEN ≤ 15%` → pass, `WATCH 15–30%`
     → log + alert + pass, `HALT > 30%` → reject. Boundaries inclusive on the
     lower tier (exactly 15% = GREEN, exactly 30% = WATCH).
   - `LIVE_SIZE_CAPS_USDC = {"btc/5m": 500.0, "eth/5m": 100.0}` (owner pick).
   - `classify_slippage_tier`, `live_size_cap_for_cell`, `evaluate_slippage_gate`,
     `normalise_cell` — all pure/deterministic, no DB/async/network/clock.

2. **Wired into `domain/risk/gate.py:evaluate`** as step "14b", immediately after
   the market-impact ratio guard (step 14) and before the per-user LIVE capital
   cap (step 15). It runs **only when `chosen_mode == "live"`**:
   - Estimates slippage magnitude via the existing pure
     `domain/research/slippage_estimator.estimate_slippage_bps` (lazy-imported in
     the live branch to keep the risk-gate module-import DB-free), using
     `final_size`, `ctx.orderbook_depth_usdc` (→ falls back to `market_liquidity`),
     `ctx.spread` (→ falls back to 1.0 = zero spread cost), and `ctx.proposed_price`.
   - Gross-edge denominator is `ctx.edge_bps` (already on the context).
   - HALT or a per-cell size-cap breach → `GateResult(False, reason, 14)` cleanly,
     **no exception**. Reasons: `slippage_halt`, `slippage_live_size_cap`.
   - WATCH → structured `logger.warning("slippage_watch …")` + Sentry breadcrumb
     (`category="risk.slippage"`, fail-soft), then pass through.
   - GREEN → pass.

`GateContext` gained three optional/defaulted fields (`cell`, `orderbook_depth_usdc`,
`spread`) so the five existing construction sites are byte-unchanged.

### Design decision — LIVE-only (safety-critical)

The gate is scoped to the LIVE-routed path on purpose. Paper trades (~$7) leave
the size-dependent impact term dormant, AND paper accrual is the data feeding the
WARP-86 EV grid-sweep and the WARP-78 cutover decision. Gating paper on slippage
would alter that accrual and corrupt the analysis it informs. Sub-Lane C is
explicitly the LIVE cutover instrument, so the gate fires only for a trade the
gate is about to route `chosen_mode='live'`. **Net effect in production today
(everything is paper): zero runtime change.** The gate activates at LIVE cutover.

## 2. Current system architecture

```
RISK gate (domain/risk/gate.py:evaluate) — steps 0..15
  …
  13. market status + size cap + chosen_mode (live|paper) selection
  14. market-impact ratio guard (size/liquidity)            domain/execution/slippage.py
  14b. tiered slippage gate  [chosen_mode=='live' only]     domain/risk/slippage_gate.py   ← NEW
        slippage_bps = estimate_slippage_bps(...)           domain/research/slippage_estimator.py (pure)
        verdict      = evaluate_slippage_gate(cell, size, slippage_bps, edge_bps)
          • size-cap breach (btc>$500 / eth>$100) → reject  slippage_live_size_cap
          • HALT (>30% of edge)                   → reject  slippage_halt
          • WATCH (15–30%)  → log + Sentry breadcrumb → pass
          • GREEN (≤15%)                                  → pass
  15. per-user LIVE capital cap
```

Pipeline compliance (CLAUDE.md SYSTEM PIPELINE — LOCKED): the slippage gate lives
in **RISK only**, runs before EXECUTION, no stage skipped.

## 3. Files created / modified

- Created: `projects/polymarket/crusaderbot/domain/risk/slippage_gate.py`
- Modified: `projects/polymarket/crusaderbot/domain/risk/gate.py`
  (lazy estimator import in the live branch; 3 optional `GateContext` fields;
  the step-14b live-only slippage block)
- Created: `projects/polymarket/crusaderbot/tests/test_slippage_gate.py`
- Modified: `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- Modified: `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- `pytest projects/polymarket/crusaderbot/tests/test_slippage_gate.py` → **17 passed**.
  Coverage: one test per tier (GREEN/WATCH/HALT) on mock slippage values, tier
  boundary inclusivity, HALT on non-positive/missing/non-finite edge, the locked
  cap values + case/whitespace-insensitive cell lookup, size-cap breach reject
  (`slippage_live_size_cap`), size-cap exact-boundary pass, unknown-cell no-cap,
  HALT-on-missing-edge-within-cap, and a realistic estimator → gate integration
  (eth/5m at the $100 cap with depth ~7.2k / spread 1.0104 → strictly GREEN,
  validating the launch cap keeps eth/5m GREEN).
- `ruff check` on all three touched files → clean.
- `python -m py_compile` on `slippage_gate.py` + `gate.py` → clean.
- No DB / asyncpg / async call added to the per-candidate hot path — the estimator
  is pure and the tier/cap verdict is a pure function (directly honours the #1694
  pool-wedge lesson).

## 5. Known issues

- **`GateContext.cell` / `orderbook_depth_usdc` / `spread` are not yet populated**
  at the candidate construction sites (those files are outside the D1 scope lock).
  Until the follow-up lane threads them: `cell=None` → the per-cell LIVE size cap
  does not fire (the tier gate still fires using `market_liquidity` as the depth
  proxy and `edge_bps` as the denominator). This is why the claim is NARROW
  INTEGRATION, not FULL RUNTIME — the gate logic is live and correct, but the
  per-cell caps need the cell label threaded from the candidate source to bind on
  real LIVE flow. This matches the proposal's "follow-up lane wires the chosen gate".
- **Edge denominator is paper-fill edge** (proposal §5): `edge_bps` is measured on
  paper fills, so the % -of-edge figures are optimistic — a reason the owner-locked
  caps are conservative.
- The new test file is placed in the existing flat `tests/` dir
  (`tests/test_slippage_gate.py`), matching the repo's risk-gate test convention
  (`test_concurrency_policy.py`, `test_robustness_gate.py`), since there is no
  `tests/risk/` package — the directive allowed an "equivalent test dir".

## 6. What is next

- WARP🔹CMD review (tiers + caps already owner-picked in the directive).
- Follow-up lane (separate branch, outside this scope lock): thread `cell`,
  `orderbook_depth_usdc`, `spread` from each candidate source into `GateContext`
  so the per-cell size caps + tier gate bind on real LIVE data; compose with the
  WARP-78 EV cutover gate; this closes the WARP-79 §1.7 verdict blocker end-to-end.
- Validate the modeled impact term against real LIVE fills in the first LIVE week;
  re-tune caps.

---

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: tiered LIVE slippage gate + per-cell caps wired into the RISK
gate live path, pure hot path, GREEN/WATCH/HALT + size-cap reject behaviour.
Not in Scope: candidate-site population of cell/depth/spread; EV cutover gate;
sizing/strategy changes.
Suggested Next Step: WARP🔹CMD review.
