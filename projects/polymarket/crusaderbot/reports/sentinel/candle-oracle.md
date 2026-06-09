# WARP•SENTINEL Validation — candle-oracle (WARP-65, Chunk 4/4)

Role: WARP•SENTINEL
Branch: WARP/sentinel-candle-oracle
Linear: WARP-65 · Parent: WARP-61 · Validates: WARP-62 + WARP-63 + WARP-64 (all MERGED to main @ a92fec2)
Date: 2026-06-04 11:20 Asia/Jakarta

## Environment

`dev` — code-truth audit. This lane (the candle oracle edge engine) has **zero
infra / Telegram / execution surface** to enforce: it is flag-gated OFF, PAPER-only,
and Chunk 3 is ADVISORY (computes/logs, never trades). Infra (Redis/PG/Influx) and
Telegram enforcement are therefore N/A for this validation. Validation is against
actual merged code + executable evidence, not report wording.

## Validation Context

- Validation Target: oracle edge engine — RTDS multi-asset client (Chunk 1),
  per-asset fair-value/edge calc (Chunk 2), advisory wiring into late_entry_v3 +
  lazy oracle singleton lifecycle (Chunk 3).
- Declared Claim Levels: FOUNDATION (Chunks 1-2), NARROW INTEGRATION (Chunk 3).
- Tier: MAJOR. Default posture: UNSAFE until proven.
- Scope note: WARP-64 was reduced to ADVISORY-ONLY by explicit WARP🔹CMD direction
  (recorded in forge report + PROJECT_STATE + PR #1603). The WARP-65 test-plan line
  "trades fire ONLY when distance/edge/trend pass" therefore validates as **N/A by
  design** — there is no hard gate yet (see Broader Audit Finding). Validation is
  against the as-built advisory claim.

## Phase 0 Checks (all PASS)

- Forge reports present at correct path, all 6 sections: reports/forge/oracle-chainlink-client.md,
  oracle-fairvalue-calc.md, oracle-strategy-wiring.md → PASS.
- PROJECT_STATE.md updated (full timestamp 2026-06-04, ASCII section labels) → PASS.
- No `phase*/` folders anywhere in PROJECT_ROOT → PASS.
- Domain structure correct (oracle layer under domain/strategy/oracle/) → PASS.
- Implementation evidence exists for all claimed paths (83 tests pass) → PASS.

## Findings (evidence — file:line)

F1. FUNCTIONAL — fair-value math is correct (independently hand-verified, not just
    test-trusted). `compute_fair_value` (domain/strategy/oracle/fair_value.py:125)
    = `0.5*(1+erf(z/√2))` with `z = delta/(sigma*√t)`. SENTINEL recomputed Φ(z) by
    hand for delta=0.0015 / t=120s: BTC 0.9145, ETH 0.8539, SOL 0.7532 — exact match
    to code (Δ<1e-12). Per-asset sigma is materially different (SOL>ETH>BTC), proving
    the per-asset wiring (sigma_for_asset, fair_value.py:85). PASS.

F2. FAILURE MODES — fail-soft, never fabricates. Verified by execution:
    time_left→0 saturates 1.0/0.0 (fair_value.py:149); delta=0→0.5 (:144); denominator
    underflow→zero-variance bound, no ZeroDivisionError (:158); missing/None/≤0 best-ask
    → 0.01 CLOB tick floor (_normalize_ask, :180); NaN/inf→ValueError (_require_finite,
    :67). RTDS get_price returns None (never a stale value) past ORACLE_STALENESS_SEC
    and logs the drop (rtds.py get_price). PASS.

F3. SAFETY-CRITICAL — advisory has ZERO capital-path effect. `_observe_oracle_edge`
    (late_entry_v3.py) is invoked AFTER every existing gate passes, its result merged
    into candidate.metadata only; `_evaluate_market` still returns `(candidate, None)`
    unchanged. Grep across services/domain/webtrader/bot/jobs for any consumer of
    `oracle_edge_would_pass`/`oracle_edge_*` → ONLY a comment in signal_scan_job:3594;
    NO code gates/branches on it. The advisory observation cannot reject, resize, or
    redirect a trade. PASS.

F4. SAFETY-CRITICAL — risk/execution/live-guard untouched. `git diff fbe2abd~1..a92fec2`
    over domain/risk/ + domain/execution/ = empty; no change to ENABLE_LIVE_TRADING or
    Kelly in config.py. RISK still runs before EXECUTION (the advisory sits in the
    STRATEGY stage, well upstream). PASS.

F5. ASYNC SAFETY — asyncio only, no threading. No `threading`/`Thread(` in
    domain/strategy/oracle/. The oracle singleton uses `asyncio.Lock` + `create_task`
    (signal_scan_job get_candle_oracle). Double-checked-lock init; `stop_candle_oracle`
    now acquires the same lock (review fix e44a37c) closing the start/stop race. PASS.

F6. LIFECYCLE — lazy singleton honors the 3 owner requirements: owns its run-loop
    task (PolymarketRTDSOracle.start), started once + reused across scans (no per-scan
    reconnect — module global guard), warmup-tolerant (None pre-first-tick →
    "oracle warming up" log, status=warming_up, no error), best-effort stop wired into
    main.lifespan shutdown (main.py) so the WS task cannot leak. PASS.

F7. ISOLATION — two flags default OFF (config.py ORACLE_ENABLED=False,
    ORACLE_EDGE_GATE_ENABLED=False); `_build_oracle_edge_cfg` returns None unless BOTH
    on, and `oracle_from_settings` raises OracleDisabledError when ORACLE_ENABLED off
    (caught → inert). With either off, behaviour is byte-identical to pre-lane (110
    candle/scan regression tests pass). PASS.

## Score Breakdown

- Architecture 20% → 19 (clean package, injectable seams, mirrors integrations/clob/ws.py)
- Functional 20% → 19 (math hand-verified; live RTDS frame unexercised — see advisory)
- Failure modes 20% → 20 (every degenerate path fail-soft; no fabrication)
- Risk 20% → 20 (capital path + guards provably untouched; advisory inert)
- Infra+Telegram 10% → 9 (N/A surface; nothing degraded)
- Latency 10% → 9 (O(1) cache read + trivial math; no measured concern)
- TOTAL: 96/100

## Critical Issues

None found.

## Status

APPROVED — Score 96/100, 0 critical. Safe for merge of the SENTINEL sync; the
candle oracle epic (Chunks 1-3) is paper-safe, flag-OFF, advisory, and provably
isolated from the capital path.

## PR Gate Result

Source WARP•FORGE PRs (#1601/#1602/#1603) are already MERGED to main. This SENTINEL
report + PROJECT_STATE sync target `main` (per AGENTS.md: when the source FORGE PR is
already merged, the SENTINEL PR targets main). No direct-to-main bypass of an open
source lane.

## Broader Audit Finding

The original WARP-65 test plan assumed Chunk 3 hard-gates trades on edge. The as-built
is ADVISORY-ONLY by explicit owner direction — a deliberate, documented scope decision,
NOT a defect. Consequence: the edge engine currently produces zero trading effect;
its value is telemetry until a follow-up flips `would_pass` into a pre-EXECUTION reject.
That follow-up is gated on the conditions below and will itself require WARP•SENTINEL
re-validation (it is the actual capital-path change).

## Reasoning

Every reachable path is safe-by-construction: flags OFF → inert; flags ON → advisory
observation that is fail-soft (any oracle error/warmup/parse-miss → None/status, never
a fabricated price, never a trade). The fair-value math is provably correct and
per-asset. There is no path by which this lane can place, resize, or block a trade, so
no critical safety risk exists at the declared claim level. APPROVED.

## Fix Recommendations

None blocking. Carry-forward conditions for the FUTURE hard-gating follow-up (not this
lane):
1. Verify the live `wss://ws-live-data.polymarket.com` frame shape against a real
   session before any `would_pass`→reject flip (the RTDS subscribe/parse format in
   rtds.py is defensive-but-unverified-live).
2. Add the rolling recent-delta momentum history so flip_hunter "Trend" can actually be
   enforced (currently a recorded flag only).
3. Re-run WARP•SENTINEL MAJOR validation on the hard-gating change (it is the real
   capital-path edit).

## Out-of-scope Advisory

Live activation remains a WARP🔹CMD/owner decision. Parameter (sigma / Distance / Min
Edge) re-calibration and non-candle presets are out of scope.

## Deferred Minor Backlog

- [DEFERRED] Advisory edge is stamped on emitted (passed-gate) candidates only, not on
  rejected markets — full-funnel telemetry is a future enhancement, not a defect.

## Telegram Visual Preview

N/A — this lane has no Telegram surface (advisory backend telemetry only; no alert
events, no dashboard, no operator commands added).
