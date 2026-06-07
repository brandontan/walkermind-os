# WARP-83 Sub-Lane C — Cutover Slippage Gate Thresholds (Proposal)

Validation Tier: STANDARD
Claim Level: FOUNDATION
Validation Target: a data-grounded PROPOSAL for the LIVE-cutover slippage gate —
tiered thresholds + per-cell position-size caps — derived from the Phase 2b
calibrated estimator at LIVE-realistic notional. Proposal only; no code, no gate
change. WARP🔹CMD decides.
Not in Scope: implementing the gate in code; changing `SLIPPAGE_PNL_GATE_FRAC` or
any sizing constant; the EV/decision-criteria cutover gate (WARP-78 — this is the
slippage layer that composes with it).
Suggested Next Step: WARP🔹CMD picks a tier set + per-cell caps; a follow-up lane
wires the chosen thresholds into the cutover gate.

---

## 1. What was built

A proposal for the slippage component of the LIVE cutover gate. Phase 2b proved the
calibrated slippage gate is benign at **paper** sizing (6.1% of gross P&L), but paper
trades are ~$7 — the size-dependent market-impact term is effectively dormant. This
lane re-evaluates the **same calibrated model at LIVE-realistic notional** so the
cutover gate is set against the sizing that will actually trade, not the paper proxy.

Method: the merged calibrated estimator
(`max(0, spread-1.0)·0.5·1e4` spread + `0.02·sqrt(stake/depth)·1e4` impact) recomputed
per real trade with the paper stake replaced by fixed LIVE stakes
{$50, $100, $250, $500, $1k, $5k}, using each trade's **actual** book depth, then
aggregated per cell. Gross edge per cell (bps of notional) is the denominator. SQL
replication against Supabase `ykyagjdeqcgcktnpdhes` (no `DATABASE_URL` in CC); DB
output treated as untrusted. Snapshot: current `paper_real`, btc/5m + eth/5m (the
target cutover cells; thin 15m/sol cells are out of cutover scope per WARP-78).

## 2. Current system architecture

No runtime change. The proposal targets the existing slippage gate seam in
`scripts/replay_with_slippage.py` (`SLIPPAGE_PNL_GATE_FRAC`, currently a single 50%
catastrophic backstop) and composes with the WARP-78 EV cutover decision criteria.

```
LIVE cutover decision = EV gate (WARP-78)  AND  slippage gate (this proposal)
slippage gate input   = calibrated slippage(bps) at the PLANNED LIVE per-trade
                        notional, per cell, ÷ that cell's gross edge (bps)
```

## 3. Files created / modified

- Created: `projects/polymarket/crusaderbot/reports/forge/cutover-slippage-thresholds.md`
- Modified: `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- Modified: `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

### 4.1 Calibrated slippage vs LIVE stake (real per-trade depth)

Slippage as **% of that cell's gross edge** (slip bps ÷ edge bps). The spread
component (~52 bps) is size-independent; only the impact term grows with stake.

| Stake | btc/5m avg bps | btc/5m % of edge | eth/5m avg bps | eth/5m % of edge |
|---|---|---|---|---|
| $50 | 64.7 | 4.5% | 71.9 | 11.8% |
| $100 | 70.0 | 4.9% | 79.9 | 13.1% |
| $250 | 80.5 | 5.6% | 95.6 | 15.6% |
| $500 | 92.3 | 6.4% | 113.3 | 18.5% |
| $1,000 | 109.0 | 7.6% | 138.4 | 22.6% |
| $5,000 | 179.7 | 12.5% | 241.9 | 39.5% |

Cell context (Sub-Lane D): btc/5m edge **+1,436 bps**, depth p50 **14.5k**; eth/5m
edge **+612 bps**, depth p50 **7.2k**.

### 4.2 Read — eth/5m is the binding constraint

- **btc/5m stays comfortable to large size**: deep book + strong edge → only 12.5% of
  edge consumed even at $5k. Slippage is not the cutover risk for this cell.
- **eth/5m degrades fast**: lower edge (less than half btc/5m) over a shallower book →
  18.5% of edge at $500, **39.5% at $5k**. eth/5m sets the binding LIVE size constraint.
- Across both, **no stake breaches the legacy 50% catastrophic gate** — confirming the
  Phase 2b conclusion holds at LIVE sizing too, but with a clear per-cell ceiling.
- The 50% single-line gate is **too lenient** for a go/no-go cutover decision: eth/5m
  at $5k (39.5%) passes 50% yet hands ~40% of its edge to execution cost. A tiered,
  per-cell gate is the right instrument.

### 4.3 Proposed gate (for CMD decision)

**Tiered slippage-of-edge thresholds** (applied per cell, at the planned LIVE notional):

| Tier | Slippage ÷ gross edge | Cutover action |
|---|---|---|
| GREEN | ≤ 15% | Cutover OK at the planned size |
| WATCH | 15% – 30% | Cutover allowed only at reduced size; monitor per-cell |
| HALT | > 30% | No cutover for that cell at that size (well below the old 50%) |

**Resulting per-cell LIVE size caps** (largest tested stake keeping ≤ 15% GREEN):

| Cell | GREEN up to | WATCH band | HALT onset |
|---|---|---|---|
| btc/5m | ≥ $5,000 (12.5% @ $5k) | not reached in tested range | not reached ≤ $5k |
| eth/5m | ~$100 (13.1% @ $100; $250 is already 15.6% = WATCH) | ~$100 – ~$3k | ~$5k (39.5%) |

**Recommendation:** adopt the GREEN ≤15% / WATCH 15–30% / HALT >30% tiers and an
**initial LIVE per-trade cap of ~$100 on eth/5m and ~$1–2k on btc/5m**, re-tuned after
the first LIVE week. (eth/5m's largest *strictly* GREEN tested stake is $100 at 13.1%;
$250 already crosses into WATCH at 15.6%.) Rationale: keep both target cells in GREEN
at launch, leaving the EV gate (WARP-78) as the primary go/no-go and slippage as a
sizing constraint rather than a blocker.

## 5. Known issues

- **Edge denominator is paper-fill edge.** Gross edge (+1,436 / +612 bps) is measured on
  PAPER fills, which assume mid/though-book execution; real LIVE edge will be lower
  precisely because of the slippage modeled here. The % -of-edge figures are therefore
  **optimistic** — a reason to set caps conservatively (the recommendation does).
- **Paper→LIVE size extrapolation.** The impact term is modeled (sqrt law on real
  depth), not observed at LIVE size; first-week LIVE fills should validate it before
  raising caps.
- **Snapshot, moving window** (n≈541, last ~36 h; counts drift as data accrues). Thin
  15m/sol cells excluded (out of cutover scope, net-losing on alpha — Sub-Lane D).
- **Adverse-move component is 0 in the replay** (no live price reconstructed); real
  execution may add a small adverse-move cost on top — another reason for conservative
  initial caps.

## 6. What is next

- WARP🔹CMD picks the tier thresholds + initial per-cell caps.
- Follow-up lane: wire the chosen tiered slippage gate into the cutover decision
  (compose with the WARP-78 EV gate); replace the single 50% backstop.
- Validate the impact term against real LIVE fills in the first week; re-tune caps.
