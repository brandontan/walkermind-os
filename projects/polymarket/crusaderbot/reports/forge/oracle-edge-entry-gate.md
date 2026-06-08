# WARP•FORGE Report — oracle-edge-entry-gate

- Validation Tier: MAJOR (strategy entry logic — gates which candles trade)
- Claim Level: NARROW INTEGRATION (promotes an existing advisory verdict to a hard gate; one config flag + one OracleEdgeConfig field + one predicate)
- Validation Target: `_oracle_edge_hard_rejects` predicate, its wiring in `late_entry_v3._evaluate_market`, the `ORACLE_EDGE_HARD_REJECT_ENABLED` config flag, and `OracleEdgeConfig.hard_reject` threaded by `_build_oracle_edge_cfg`.
- Not in Scope: the oracle fair-value / edge / distance computation itself (unchanged), the per-preset bands in `_CANDLE_PRESET_EDGE` (unchanged — already Kreo-aligned), the trend filter (NOT enforced — `would_pass` is edge+distance only), the EV scorer / score-based strategy selection (separate parked lane), the structural gates (ask_diff/spread/price-band, unchanged).
- Suggested Next Step: WARP🔹CMD review + merge; then OPERATOR enables `ORACLE_ENABLED=true` + `ORACLE_EDGE_GATE_ENABLED=true` in Fly so the gate actually engages.

---

## 1. What was built

A hard entry gate that makes `late_entry_v3` enter a candle **only when the
oracle edge + distance rules are met**, instead of entering every in-window
candle that clears the structural filters (time window, ask_diff, spread, price
band). This addresses the owner's observation (vs the Kreo bot): "bot kita hanya
lihat timenya — langsung open tanpa cek entry rules."

Key finding from the investigation: the edge + distance logic **already exists
and is already Kreo-aligned**. `_observe_oracle_edge` computes, per candle:

```
delta     = (price_now − price_open) / price_open        # signed candle move
distance  = |delta|
dist_ok   = min_dist <= distance <= max_dist
edge_ok   = max(edge_up, edge_down) >= min_edge
would_pass = dist_ok AND edge_ok          # → edge_meta["oracle_edge_would_pass"]
```

The per-preset bands (`signal_scan_job._CANDLE_PRESET_EDGE`) match the Kreo
screenshots exactly:

| Preset | Distance band | Min Edge | (Kreo screenshot) |
|---|---|---|---|
| close_sweep | 0.05%–2.0% | 2.0% | Close Sweep: 0.05%–2.00%, 2.00% ✓ |
| flip_hunter | 0.05%–5.0% | 3.0% | Early Flip Hunter: 0.05%–5.00%, 3.00% ✓ |
| safe_close | 0.03%–1.0% | 1.0% | — |

The only gap was that `would_pass` was **advisory** — logged but never enforced
(config comment: "gating to a hard reject is a deliberate follow-up"). This lane
is that follow-up: it promotes `would_pass` to a hard skip.

## 2. Current system architecture

```
late_entry_v3._evaluate_market(market, …, edge_cfg)
  ├─ structural gates: timing window, tokens, books, leg spread
  ├─ edge_meta = _observe_oracle_edge(edge_cfg, …)   # computes would_pass (unchanged)
  ├─ persist factor vector (unbiased dataset row — even for rejected candles)
  ├─ ◄── NEW: if _oracle_edge_hard_rejects(edge_cfg, edge_meta):
  │              return None, "oracle_edge_distance_reject"
  ├─ ask_diff gate, spread gate, price-band gate (unchanged)
  └─ emit SignalCandidate

_oracle_edge_hard_rejects(edge_cfg, edge_meta) -> bool   # pure, unit-tested
    return (edge_cfg is not None
            and edge_cfg.hard_reject
            and edge_meta["oracle_edge_status"] == "computed"
            and edge_meta["oracle_edge_would_pass"] is False)
```

`OracleEdgeConfig.hard_reject` is set by `_build_oracle_edge_cfg` from
`ORACLE_EDGE_HARD_REJECT_ENABLED` (default True). candle_auto inherits it for
free: it scans each sub-rule via `_scan_one_late_entry(..., preset=rule)`, each of
which builds its own `edge_cfg` with the per-rule band — so AUTO users
(e.g. qwneer8) get the gate per sub-rule.

**FAIL-OPEN is the central safety property.** The gate only fires on a `computed`
verdict. With the oracle off (`ORACLE_ENABLED=false`, current prod default),
warming up, feed_down, or stale, `edge_cfg` is None or the status is not
`computed`, so the predicate returns False and trading proceeds on the structural
gates exactly as before. A dark or degraded feed can never halt trading.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/config.py` — new
  `ORACLE_EDGE_HARD_REJECT_ENABLED: bool = True` flag + rationale.
- `projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py` —
  `OracleEdgeConfig.hard_reject` field; pure `_oracle_edge_hard_rejects`
  predicate; enforcement in `_evaluate_market` (reason
  `oracle_edge_distance_reject`).
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` —
  `_build_oracle_edge_cfg` sets `hard_reject` from the config flag.

Created:
- `projects/polymarket/crusaderbot/tests/test_oracle_edge_hard_gate.py` — 15 tests.

Report / state:
- `projects/polymarket/crusaderbot/reports/forge/oracle-edge-entry-gate.md` (this file).
- `PROJECT_STATE.md`, `CHANGELOG.md` updated.

## 4. What is working

- 15 new tests pass; existing `test_oracle_edge_wiring.py` + `test_warp76_feed_loss.py`
  still pass (advisory path intact); `test_close_sweep_spread_gate.py`,
  `test_complete_set_edge_metric.py`, `test_tob_freshness_gate.py` green. `ruff` clean.
- The predicate is verified across every oracle status: `computed`+would_pass
  False → reject; `computed`+would_pass True → pass; `warming_up` / `feed_down` /
  `stale` / `error` / absent / would_pass None or missing → fail-open (no block);
  hard_reject off → no block; cfg None → no block.
- Config flag default ON; env override both directions verified.
- Zero behaviour change under the default prod config (oracle off) — the gate is
  inert until the oracle is enabled, so this merges safely with no paper-data
  discontinuity until the operator opts in.

## 5. Known issues

- **Activation requires the oracle.** The gate does nothing until the operator
  sets `ORACLE_ENABLED=true` AND `ORACLE_EDGE_GATE_ENABLED=true` in Fly (those
  build `edge_cfg` and run the RTDS feed). `ORACLE_EDGE_HARD_REJECT_ENABLED` is
  default ON so that enforcement begins the moment the oracle goes live — no
  second flip needed — but the selectivity the owner wants only appears once the
  oracle feed is running and producing `computed` verdicts.
- **`would_pass` uses max-edge, not entry-side edge.** It enforces
  `max(edge_up, edge_down) >= min_edge` (the existing advisory definition), not
  the edge of the specific side that will be entered. For the favored-side
  (standard) entry these usually coincide; refining the gate to the entry-side
  edge (as the smart-strike-real-edge lane does for the LIVE slippage tier) is a
  possible follow-up, deliberately out of scope to keep this faithful to the
  established `would_pass` metric.
- **Trend not enforced.** `would_pass` is distance + edge only (the trend flag is
  advisory in `_observe_oracle_edge`). This matches the owner's pick (edge +
  distance, no trend). A trend gate would be a separate addition.

## 6. What is next

- WARP🔹CMD review + merge (MAJOR Stop Condition — not self-merged).
- OPERATOR: enable `ORACLE_ENABLED=true` + `ORACLE_EDGE_GATE_ENABLED=true` in Fly,
  then observe scan logs for `oracle_edge_distance_reject` skips and confirm
  entries drop to only edge/distance-qualified candles (Kreo-like selectivity).
- SEPARATE LANE (NOT in this PR): score-based strategy selection ("highest score
  wins" in the candle_auto diagram). The EV scorer is parked because WARP-78
  Phase 0 found it structurally broken (degenerate rules, biased label, edge ≪
  noise); activating it as-is would make selection effectively random. Our three
  sub-rules are also largely time-disjoint within a candle, so score-vs-precedence
  selection changes little in practice without a sound cross-cell scorer. The
  responsible path is the WARP-78 Phase 1 rebuild (fix the realized-EV label,
  revive Volatility/Momentum), CMD-owned — NOT a flip of the broken switch.
