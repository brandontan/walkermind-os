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

## STABILITY SCORE

- Architecture (20): 20 — additive, reuses copy-trade infra, no new authority.
- Functional (20): 20 — claim logic + source fully covered (16 tests).
- Failure modes (20): 19 — fail-soft throughout; −1 side-classification fidelity (M-1).
- Risk integrity (20): 20 — gate/execution/Kelly/live-guard untouched, no bypass.
- Infra (10): 10 — DB-backed, zero new scan-loop external calls.
- Latency/cost (10): 10 — flow-gated + capped far band, batched query.
- **TOTAL: 99/100** → adjusted **96/100** for the disclosed M-1 data-fidelity caveat.

## GO-LIVE STATUS

**APPROVED — 96/100, 0 critical.** Paper-only, `PLAYBOOK_STRATEGY_ENABLED`-gated; no LIVE
capital path touched. Safe to merge at WARP🔹CMD's discretion + Fly redeploy.

## FIX RECOMMENDATIONS (non-blocking)

- M-1 (MEDIUM, disclosed): `heisenberg_realtime_trades.side` is normalised yes/buy/long →
  YES, no/sell/short → NO. If a row stores a BUY/SELL *direction* of the NO token, this
  conflates direction with outcome. Affects signal fidelity, not capital safety (paper).
  Recommend confirming the stored `side` domain and refining classification in Phase-2c
  alongside backtest calibration of the tunables (win_rate≥0.65, 24h, $500, 0.20).
- L-1 (LOW): tunables are first-pass — validate OOS in the Phase-2c backtest before any
  LIVE scaling.

## TELEGRAM PREVIEW

N/A — no new Telegram surface in this lane (signal-only; existing PLAYBOOK alerts unchanged).
