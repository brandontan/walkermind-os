# WARP•SENTINEL — playbook-sharp-money (WARP-53 Phase-2b)

Branch: `WARP/ROOT/playbook-sharp-money` · PR #1577 · Tier: **MAJOR**
Validator: WARP•SENTINEL (WARP•R00T acting, owner-authorised — "Go")
Default posture: system UNSAFE until proven. Code is truth.

## TEST PLAN

Scope: native Sharp Money signal — DB-backed `fetch_sharp_flows` source, activated
`SharpMoneyModule`, strategy far-band wiring, and the Codex P1 far-band fix. Paper-only,
`PLAYBOOK_STRATEGY_ENABLED`-gated. Phases run: 0 pre-test, 1 functional, 2 pipeline, 3
failure modes, 4 async safety, 5 risk-rule integrity, 6 latency/cost. Env: dev (paper).

## FINDINGS (per phase, evidence cited)

Phase 0 — Pre-test: **PASS**
- Forge report present, 6 sections + metadata — `reports/forge/playbook-sharp-money.md`.
- `PROJECT_STATE.md` / `WORKTODO.md` / `CHANGELOG.md` updated (surgical).
- Zero `phase*/` folders; no shims; diff scoped to `domain/playbook/*`, the strategy,
  report + state only (`git diff --stat origin/main...HEAD`).

Phase 1 — Functional: **PASS**
- `SharpMoneyModule.evaluate` (`domain/playbook/modules.py:172+`): TTL>24h gate, $500 flow
  floor, 0.20 confidence floor, side = sign(imbalance), TP0.30/SL0.15 + metadata.
- Module exit envelope is honoured: `evaluate_snapshot` stamps `applied_tp_pct` /
  `applied_sl_pct` from the winning module — required by `_build_trade_signal:1812`
  (see Codex P2 below). 18 sharp-money + 31 engine + 82 scan = **131 pass** (0 fail).

Phase 2 — Pipeline (no bypass): **PASS**
- Module emits a standard `SignalCandidate` via `evaluate_snapshot`; the dispatch →
  `_process_candidate` → 13-step risk gate → execution path is **not in the diff**
  (`git diff --name-only origin/main...HEAD` → no signal_scan_job/engine/gate/risk/live).
- Far band markets are upserted via the shared `select_sports_markets_in_window` so
  candidates resolve in `_load_market` (closes the #1572-class not-synced skip).

Phase 3 — Failure modes: **PASS**
- `fetch_sharp_flows` is fail-soft: any DB error → `{}` (`sharp_flow.py:85`), empty
  `condition_ids` → `{}` (no query), zero/negative total flow rows skipped.
- Empty/absent `leaderboard_stats` or `heisenberg_realtime_trades` → no sharp flow →
  Sharp Money abstains; Closing Edge unaffected (fail-safe degradation).
- Per-market orderbook fetch remains fail-soft per market in `_fetch_sports_snapshots`.

Phase 4 — Async safety: **PASS**
- `asyncio` only; proper `async with pool.acquire()` (`sharp_flow.py:63`); no `threading`;
  no shared mutable state across awaits. Pure decision core elsewhere.

Phase 5 — Risk-rule integrity: **PASS**
- Risk gate / execution / fractional Kelly (a=0.25) / position caps / `ENABLE_LIVE_TRADING`
  **untouched** (absent from the code diff). Module size = `suggested_size_usdc`; the gate
  remains authoritative re-sizer. No guard bypass. Paper-only + operator-flag-gated.

Phase 6 — Latency / scan cost: **PASS**
- Far band (24h–72h) is **flow-gated before any orderbook fetch**: one batched
  `ANY($1)` aggregate query, then book reads only for far markets with real sharp flow,
  capped at 20 (`_MAX_SHARP_MARKETS_PER_SCAN`); near band keeps 40. SQL fully
  parameterized `$1–$4` (`sharp_flow.py:77-80`) — no injection.

## CRITICAL ISSUES

None remaining.
- Codex P1 (Sharp Money DOA — snapshot window ≤2h vs module TTL>24h) fixed in `cd0e193`:
  flow-gated far band; verified by `test_window_includes_far_band_*` +
  `test_router_routes_sharp_money_far_from_event`.
- Codex P2 (module TP/SL not applied — `_build_trade_signal:1812` only honours
  `applied_tp_pct`/`applied_sl_pct`, which PLAYBOOK did not stamp) **caught during this
  audit and fixed in-lane**: `evaluate_snapshot` now stamps the winning module's TP/SL
  (mirrors the candle_auto router convention at `signal_scan_job:3533`); verified by
  `test_evaluate_snapshot_stamps_sharp_module_tpsl` (30/15) +
  `..._closing_edge_tpsl` (25/12). This also repaired the pre-existing latent gap for
  Closing Edge.
- Codex P1 / SENTINEL M-1 (signed-flow direction) — the stored `side` column is
  `side or direction or outcome` upstream, so classifying a `BUY` of the NO token as
  YES-accumulation could FLIP the emitted trade side. This audit's M-1 caveat was
  **escalated and fixed in-lane** (`c…`): sign now = outcome_sign × action_sign via a
  unit-tested `yes_accumulation_signed` (`sharp_flow.py`), outcome from `raw->>'outcome'`
  (the field the copy-trade path already trusts); ambiguous rows contribute magnitude-only
  and can never flip the side. Verified by an 8-case direction matrix +
  `test_fetch_sharp_flows_ambiguous_counts_total_not_signed`.

## STABILITY SCORE

- Architecture (20): 20 — additive, reuses copy-trade infra, no new authority.
- Functional (20): 20 — claim logic, signed-flow direction, and source fully covered.
- Failure modes (20): 20 — fail-soft throughout; the M-1 direction risk is fixed +
  unit-tested (ambiguous rows never flip the side).
- Risk integrity (20): 20 — gate/execution/Kelly/live-guard untouched, no bypass.
- Infra (10): 10 — DB-backed, zero new scan-loop external calls.
- Latency/cost (10): 9 — per-trade fetch + Python aggregation (bounded: ≤50 sharp
  wallets × ≤20 far markets × 24h); −1 vs in-SQL aggregation, traded for testable sign
  logic — a sound call.
- **TOTAL: 99/100** → **APPROVED at 98/100** (−1 latency/cost only).

Evidence: 27 sharp-money + 31 engine + 82 scan = **140 pass**, ruff + py_compile clean.

## GO-LIVE STATUS

**APPROVED — 98/100, 0 critical.** Paper-only, `PLAYBOOK_STRATEGY_ENABLED`-gated; no LIVE
capital path touched. Three bot-review findings (Codex P1 window, Codex P2 TP/SL, Codex P1
flow direction) all caught/fixed in-lane with tests. Safe to merge at WARP🔹CMD's
discretion + Fly redeploy.

## FIX RECOMMENDATIONS (non-blocking)

- L-1 (LOW): tunables are first-pass — validate OOS in the Phase-2c backtest before any
  LIVE scaling; confirm the upstream `outcome` field coverage in `raw` against live data
  so the signed/total ratio is not over-dampened by ambiguous rows.

## TELEGRAM PREVIEW

N/A — no new Telegram surface in this lane (signal-only; existing PLAYBOOK alerts unchanged).
