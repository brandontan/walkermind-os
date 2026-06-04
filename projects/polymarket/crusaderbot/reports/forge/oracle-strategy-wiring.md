# WARP•FORGE Report — oracle-strategy-wiring

Role: WARP•R00T (operating as WARP•FORGE for this build lane)
Branch: WARP/ROOT/oracle-strategy-wiring
Linear: WARP-64 (Chunk 3/4) · Parent: WARP-61 · Blocks: WARP-65 (Chunk 4) · Blocked-by: WARP-62 + WARP-63 (both MERGED)
Date: 2026-06-04 10:55 Asia/Jakarta

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : Advisory oracle-edge wiring into the late_entry_v3 scan path
                    (BTC/ETH/SOL) + the lazy RTDS-oracle singleton lifecycle in
                    signal_scan_job + per-preset Distance/Min-Edge/Trend params.
                    Network stubbed; edge observation is non-blocking.
Not in Scope      : Hard edge gating (rejecting trades on edge — deliberate
                    follow-up after live RTDS verification), Trend-align
                    enforcement (needs momentum history), live activation, sigma
                    re-calibration, non-candle presets, exit logic.
Suggested Next    : WARP•SENTINEL MAJOR validation (WARP-65, Chunk 4).

---

## 1. What was built

The wiring that connects the merged oracle (Chunk 1, RTDS multi-asset price
stream) and fair-value calculator (Chunk 2, per-asset sigma) into the
`late_entry_v3` candle strategy — as an **ADVISORY** signal per WARP🔹CMD
direction. For every would-trade candidate the strategy now computes, logs, and
stamps the oracle fair-value/edge (`delta`, `fair_up`, `edge_up`/`edge_down`,
`distance`, `would_pass`) across BTC/ETH/SOL. It does **not** block any trade
this chunk — flipping `would_pass` into a hard reject is a deliberate follow-up
after the live RTDS frame format is verified.

Everything is gated behind two flags, both default **OFF**:
`ORACLE_EDGE_GATE_ENABLED` (wire the advisory observation) AND `ORACLE_ENABLED`
(the RTDS feed actually runs). With either off, behaviour is byte-identical to
today's `ask_diff` strategy.

The RTDS oracle is provisioned as a **lazy singleton** in `signal_scan_job`:
started once on first use, reused across every scan (no per-scan reconnect),
warmup-tolerant (a `None` price before the first tick is normal and logged, never
an error), and stopped best-effort at app shutdown so its WS run-loop task does
not leak.

## 2. Current system architecture (relevant slice)

```
signal_scan_job._scan_one_late_entry(strat, pp, ..., preset)
  ├─ _build_oracle_edge_cfg(preset)                 # flag-gated, fail-soft
  │    ├─ get_candle_oracle()                       # lazy singleton (start once)
  │    │    └─ oracle_from_settings().start()       # ORACLE_ENABLED required
  │    └─ OracleEdgeConfig(price_provider=oracle.get_price,
  │         sigma_map=Settings.oracle_sigma_per_sqrt_sec,
  │         min_dist/max_dist/min_edge/trend = _CANDLE_PRESET_EDGE[preset])
  └─ LateEntryV3Strategy.scan(..., edge_cfg)
       └─ _evaluate_market(..., edge_cfg)            # existing gates UNCHANGED
            └─ _observe_oracle_edge(edge_cfg, ...)   # ADVISORY: compute+log+stamp
                 ├─ symbol  = _asset_base_from_slug(slug) + "/usd"
                 ├─ price   = edge_cfg.price_provider(symbol)   # None = warmup
                 ├─ ptb     = get_price_to_beat(market)         # Chunk 1
                 ├─ delta   = compute_delta(price, ptb)         # Chunk 2
                 ├─ fair_up = compute_fair_value(delta, secs, sigma_for_asset)
                 └─ edge    = compute_edge(fair_up, yes_ask, no_ask)
                              -> stamped into candidate.metadata (no gate change)

main.lifespan (shutdown) -> stop_candle_oracle()    # best-effort WS task cleanup
```

- The edge observation runs on the **emitted** candidate (one that already passed
  every existing gate), right before the `SignalCandidate` is returned — the
  highest-value, lowest-noise observation set, and it cannot affect the gate.
- `_CANDLE_PRESET_EDGE` carries the Kreo-aligned per-preset Distance / Min Edge /
  Trend (fractions): close_sweep 0.05–2.0% / 2.0% / off; safe_close 0.03–1.0% /
  1.0% / off; flip_hunter 0.05–5.0% / 3.0% / with-trend. Distance band is
  `abs(delta)`; `min_edge` is a fraction; `would_pass` reflects Distance + Min
  Edge (Trend recorded as a flag, not yet enforced — see Known issues).
- RISK gate still runs before EXECUTION (untouched); exit/force-exit logic
  untouched; sizing untouched.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py`
  — oracle imports; `OracleEdgeConfig` dataclass; `_asset_base_from_slug`;
  `_observe_oracle_edge` (advisory, fail-soft); `edge_cfg` threaded through
  `scan()` + `_evaluate_market`; advisory metadata stamped onto the candidate;
  `OracleEdgeConfig` exported.
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py`
  — `_CANDLE_PRESET_EDGE`; lazy `get_candle_oracle()` singleton +
  `stop_candle_oracle()`; `_build_oracle_edge_cfg(preset)`; `_scan_one_late_entry`
  gains `preset` + builds/passes `edge_cfg`; both call sites pass the preset/rule.
- `projects/polymarket/crusaderbot/config.py` — `ORACLE_EDGE_GATE_ENABLED` flag
  (default OFF).
- `projects/polymarket/crusaderbot/main.py` — best-effort `stop_candle_oracle()`
  in the lifespan shutdown block.

Created:
- `projects/polymarket/crusaderbot/tests/test_oracle_edge_wiring.py`

State:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- `_asset_base_from_slug` maps candle slugs → `btc`/`eth`/`sol`.
- `_observe_oracle_edge`: returns `{}` when off/no-provider; `warming_up` on a
  `None` price (no error); `no_price_to_beat` when the baseline is absent;
  `computed` stamps delta/fair_up/edge_up/edge_down/distance/would_pass; swallows
  provider errors as `error` (never raises, never blocks).
- `would_pass` True for an in-band, above-min-edge candidate; False when distance
  is below `min_dist` (delta 0 → fair_up 0.5).
- `_build_oracle_edge_cfg`: `None` when `ORACLE_EDGE_GATE_ENABLED` off; `None`
  when the edge gate is on but `ORACLE_ENABLED` off (advisory stays inert);
  builds a config with per-preset params when both on.
- Lazy singleton: `oracle.start()` called once across multiple scans (reuse, no
  reconnect); `stop_candle_oracle()` stops it and resets the global; safe to call
  when never started.
- Per-preset params flow (close_sweep min_edge 0.02/trend False; flip_hunter
  0.03/True).
- 11 new wiring tests + 14 RTDS + 32 fair-value = 57 oracle tests pass. 110
  existing candle/scan regression tests pass (candle_auto router, close-sweep
  spread gate, signal_scan_job). `ruff` + `py_compile` clean.

## 5. Known issues

- **Advisory-only (by design this chunk):** `would_pass` is computed and stamped
  but never blocks a trade. The hard-gate flip is a follow-up, intentionally
  deferred until the live `wss://ws-live-data.polymarket.com` frame format is
  verified (the RTDS subscribe/parse shape in `oracle/rtds.py` is still
  best-effort/defensive).
- **Trend-align not enforced:** `flip_hunter`'s "With Trend" needs a rolling
  recent-`delta` momentum history that the single-read oracle does not yet keep.
  `would_pass` reflects Distance + Min Edge only; `trend` is recorded as a flag.
- Observation is stamped on emitted (passed-gate) candidates, not on every
  rejected market — the meaningful would-trade set. Broadening to rejected
  candidates (full funnel telemetry) is a follow-up if desired.
- Live end-to-end behaviour is unexercised (flags OFF, network stubbed) — paper
  validation belongs to WARP-65 (Chunk 4).

## 6. What is next

- WARP-65 (Chunk 4): WARP•SENTINEL MAJOR paper validation — confirm the advisory
  edge logs per candidate, the singleton lifecycle (start-once/stop), and zero
  impact on the existing gate/exit/capital path with the flags ON in paper.
- Follow-up (post-verification): verify the live RTDS frame shape, add the
  recent-delta momentum history for Trend, then flip `would_pass` from advisory
  into a hard pre-EXECUTION reject (RISK gate still before EXECUTION).
- Operator pre-activation: set `ORACLE_ENABLED=true` + `ORACLE_EDGE_GATE_ENABLED=true`
  in Fly secrets (PAPER) to begin collecting advisory edge telemetry.
