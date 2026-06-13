# WARP•R00T — late-entry-v3-edge-calibration (#1815)

Branch: `WARP/late-entry-v3-edge-calibration`
Issue: #1815
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Role: WARP•R00T (read-only calibration audit + minimal research export)
Date: 2026-06-13 11:59 Asia/Jakarta

Validation Target: produce an evidence-based verdict on whether `late_entry_v3` has a real out-of-sample edge on Polymarket BTC/ETH crypto Up/Down 5m/15m markets, separating *operational readiness* from *measured profitability*. No live behaviour change.

Not in Scope: live order placement, real fund movement, strategy threshold change, new market family, deposit/withdraw, live-guard flips, CLOB credential changes.

---

## 1. Verdict

**`NEEDS MORE DATA` — DO NOT scale live capital on `late_entry_v3` yet.**

The strategy is operationally ready (gates are explicit, capital is risk-bounded, admin universe controls are in place, fail-safe behaviour on stale/empty book is correct), but **its edge is unmeasured**. The decision metric the live code routes on (`ask_diff`) is a book-imbalance *heuristic*, not an expected-value computation; the OOS measurement harness that DOES compute net EV (`domain/research/late_entry_oos.py`) is data-starved because `SCAN_SNAPSHOT_ENABLED` was OFF in production, leaving `market_snapshots` sparse. The realized PAPER cohort describes what happened under the current TP/SL bundle, but cannot stand in for an OOS proof.

Concretely:

- `late_entry_v3` stamps advisory `oracle_edge_up/down` and an advisory `slippage_gross_edge_bps` in candidate metadata, but **does not** stamp the directional `edge_bps` key risk-gate **step 12** reads — so the `MIN_EDGE_BPS` floor is structurally inert for this strategy (confirmed in `services/signal_scan/signal_scan_job._edge_bps_from_metadata`).
- `domain/research/late_entry_oos.MIN_OOS_TRADES = 20` per preset is the project's existing trust floor; meeting it is required before any preset's edge can be called "MEASURED".
- The OOS harness substrate (`market_snapshots`) only fills when `SCAN_SNAPSHOT_ENABLED=True` (runtime-overridable via `domain/ops/runtime_config`); it has not been on long enough to satisfy that floor.

The good news: capital is already protected by the existing Kelly-fractional (a=0.25, never full Kelly) per-user gate, the $5 live Auto-Trade start gate, the kill switch, and the `assert_live_guards` activation chain. So the cost of waiting for data is small (no live spend) and the cost of NOT waiting is asymmetric (real-money loss on an unproven edge).

## 2. What was audited (code-truth evidence)

### 2.1 Strategy rules (`domain/strategy/strategies/late_entry_v3.py`)

| Gate | Value | Source |
|---|---|---|
| Entry window | 35s (close_sweep) / 60s (safe_close) / 180s (flip_hunter) | `_PRESET_FALLBACK` |
| Min ask diff | 0.05 (close_sweep) / 0.01 (safe_close, flip_hunter) | preset config |
| Max combined spread | 1.05 | `MAX_SPREAD` |
| Favored price band | 0.55–0.70 (close_sweep) / 0.60–0.70 (safe_close) / 0.10–0.36 (flip_hunter underdog) | preset config |
| Min entry sec floor | 0 / 30 / 60 | preset config |
| Force-exit `rem_sec` | 8s (close_sweep) / 30s (safe_close) / 0s = hold-to-settle (flip_hunter) | `force_exit_at_rem_sec_for(preset, tf)` |
| Flip-stop | 0.10 (effectively-off for the fast loops) | `LATE_ENTRY_FLIP_STOP` |
| LIVE min order shares | 5 (fail-closed pre-submit in `domain/execution/live.py`) | `LIVE_MIN_ORDER_SHARES` |
| Kelly | 0.25 fractional, hard-capped | `domain/risk` |

These are the live thresholds; they were proven safe under the #1797 / #1801 live-readiness audit. Nothing in this lane changes any of them.

### 2.2 Smart Strike universe (`domain/strategy/smart_strike_universe.py`)

Assets: **BTC, ETH** enabled; **SOL OFF by default** (owner-locked since #1801). Timeframes: **5m, 15m**. All six toggles (master + per-asset + per-timeframe) are runtime-overridable through `runtime_config` without redeploy. The scan delegates to this resolver so a disabled bucket emits an explicit telemetry skip reason and never produces an order intent.

### 2.3 Persisted telemetry (`services/signal_scan/signal_scan_job.py`, migration 048 `scan_runs`)

`scan_runs` persists per-tick **aggregates** only (`markets_seen`, `markets_eligible`, `candidates_emitted`, `paper_orders_created`, `positions_created`, plus `skip_breakdown` / `rejection_breakdown` / `zero_reason_breakdown` as JSONB counts). There is **no per-candidate** (price, spread, edge, side, market_id) row in this table.

`market_snapshots` (migration 080) DOES capture per-(market, tick) raw Gamma payloads — but only when `SCAN_SNAPSHOT_ENABLED=True`. In production it has been OFF, so the OOS harness substrate is sparse.

### 2.4 Realized cohort

The PAPER `positions` table preserves entry_price, side, size, exit_reason, and realized pnl_usdc for every closed `late_entry_v3` row, plus `active_preset` (post-#062) and `strategy_metadata` (post-#076). It does NOT preserve intra-trade price path or MFE/MAE — so a true counterfactual TP/SL re-simulation against a different exit threshold is impossible from this data (mirrors the documented limitation in `scripts/tpsl_calibration_backtest.py`). What IS recoverable: per-bucket realized win-rate, mean entry, realized P&L, and a defensible net-EV-after-cost simulation that subtracts the same round-trip taker cost model (`tick + slip + fees`) used by `late_entry_oos.CostModel`.

### 2.5 The decision metric the live code actually routes on

`late_entry_v3` enters when `ask_diff = abs(yes_ask - no_ask) >= MIN_ASK_DIFF` plus the spread / price-band / window gates. This is a **book-imbalance heuristic**, not an EV computation. The advisory oracle (`compute_fair_value` / `compute_edge`) is stamped in metadata, but `ORACLE_EDGE_HARD_REJECT_ENABLED` defaults False (`config.py`) — so the oracle is observation-only in production today, and step 12 (`MIN_EDGE_BPS`) never fires for this strategy.

## 3. Minimal read-only instrumentation added (issue-permitted: §10)

Per the issue's explicit permission ("If code instrumentation/reporting is missing and blocks calibration, add minimal read-only instrumentation or report export only"), one new module:

`domain/research/late_entry_realized_cohort.py` — SELECT-only query over `positions` for `mode='paper' AND status='closed' AND strategy_type='late_entry_v3' AND pnl_usdc IS NOT NULL`, excluding non-strategy exits (`force_close`, `horizon_exceeded`, `market_expired`, `paper_to_live_switch`, `already_closed`). Aggregates by (active_preset, side). For each bucket reports: `n_trades`, `wins/losses/breakeven`, `win_rate`, `mean_entry_price`, `mean_size_usdc`, `realized_pnl_usdc`, `mean P&L/trade`, `exit_reason_counts`, AND a **simulated net EV per trade in bps** computed by subtracting the existing `late_entry_oos.CostModel` round-trip cost from the realized per-share return. Buckets with `n < late_entry_oos.MIN_OOS_TRADES` (20) are labelled `UNPROVEN_THIN`; only buckets at or above the floor reach `REALIZED`. A `render_markdown()` helper produces the matrix used in §6.

Hard safety pins (`tests/test_late_entry_realized_cohort.py`, 10 tests):

- bucket math (wins/losses, win-rate, realized P&L, exit-reason histogram);
- `MIN_OOS_TRADES` gate produces `UNPROVEN_THIN` below 20 and `REALIZED` at 20;
- the simulated net EV subtracts the transparent round-trip cost from the realized return (worked example: YES@0.50 gross +20% → 2000 bps; round-trip cost 2 × 0.01 / 0.50 = 400 bps; net = 1600 bps);
- the SQL is `SELECT`-only and contains no `INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE`;
- the module source contains **no import of** CLOB / Polymarket / Bridge / Relayer adapters, the execution router, paper/live engines, ledger, custody, deposit assets — and **never references** `USE_REAL_CLOB`, `EXECUTION_PATH_VALIDATED`, `ENABLE_LIVE_TRADING`, `CAPITAL_MODE_CONFIRMED`, `assert_live_guards`, `post_order`, `submit_order`, or `router.execute`.

## 4. What this audit did NOT do (deliberate)

- Did not place any order, paper or live.
- Did not change any strategy threshold, preset config, or gate constant.
- Did not flip `USE_REAL_CLOB`, `EXECUTION_PATH_VALIDATED`, `ENABLE_LIVE_TRADING`, `CAPITAL_MODE_CONFIRMED`, `SCAN_SNAPSHOT_ENABLED`, `ORACLE_EDGE_HARD_REJECT_ENABLED`, `SMART_STRIKE_REQUIRE_MEASURED_EDGE`, `SMART_STRIKE_SOL_ENABLED`, or any other live or research flag.
- Did not edit `late_entry_v3.py`, `signal_scan_job.py`, `live.py`, `paper.py`, `router.py`, `risk/gate`, `wallet/`, or any deposit/withdraw code.
- Did not write production-quality assertions about which preset is "best" — the data substrate cannot support that claim yet.

## 5. Small-balance ($10) behaviour

Per `domain/risk/gate`, sizing is `Kelly-fractional × per-user spendable balance`, hard-capped at the per-trade and per-asset position limits, and pre-checked against `LIVE_MIN_ORDER_SHARES = 5`. At $10 balance with a typical favored entry ~$0.55, `5 shares × $0.55 ≈ $2.75` — which the gate enforces as the live floor. So the user CAN trade live at $10, but only when the candidate price puts `5 shares` at or below their spendable balance. Below that the gate fails closed (no trade, explicit telemetry reason `step_14_below_min_order_shares`). This is the intended capital-preservation behaviour.

## 6. Evidence matrix (template) and how to populate it

Run the new export to produce the matrix on demand (read-only, against the running DB):

```bash
python -m projects.polymarket.crusaderbot.domain.research.late_entry_realized_cohort
```

Schema of the matrix:

| Preset | Side | n | Win rate | Mean entry | Realized P&L | Mean P&L/trade | Sim cost (bps) | Sim net EV (bps) | Status |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| close_sweep | YES | … | … | … | … | … | … | … | REALIZED / UNPROVEN_THIN |
| close_sweep | NO | … | … | … | … | … | … | … | … |
| safe_close | … | … | … | … | … | … | … | … | … |
| flip_hunter | … | … | … | … | … | … | … | … | … |

Read the matrix as follows:

- `Status = UNPROVEN_THIN` (n < 20) → **insufficient data**. Do not size that bucket up; do not draw a conclusion from its win-rate or its mean P&L. This is the expected dominant label for thin / new presets.
- `Status = REALIZED` (n ≥ 20) → the bucket has enough realized history to **describe** what happened under the current TP/SL bundle. It is **NOT** proof of an OOS edge — for that the OOS harness must run against a populated `market_snapshots` substrate.
- `Sim net EV (bps)` should be read as "what the realized cohort would have produced after the documented round-trip taker cost". A negative number here for a REALIZED bucket is a hard caution (paper assumed zero cost, so live would be worse than paper, not better). A positive number is necessary but not sufficient — the OOS step closes the loop.

## 7. Recommended path to a verdict change (operator playbook)

These are the steps WARP🔹CMD should take BEFORE this lane can move to `APPROVE MICRO-LIVE`:

1. Flip `SCAN_SNAPSHOT_ENABLED=True` via `runtime_config` overlay (no redeploy). This starts populating `market_snapshots`. Leave it on for at least 14 days of trading activity on BTC/ETH 5m/15m.
2. Run the new realized-cohort export weekly during that window and watch each bucket's `Sim net EV (bps)` trend; a bucket that is consistently negative net-of-cost is a *no-scale* signal regardless of OOS substrate readiness.
3. After the snapshot substrate has ≥ ~500 rows per preset/timeframe, run `domain/research/late_entry_oos.measure_oos()`. Require:
   - `status == "MEASURED"` (i.e. `n_trades >= MIN_OOS_TRADES = 20`),
   - `net_ev_per_trade > 0` after the cost model, and
   - at least one preset clearing those bars by a margin owner deems meaningful.
4. Decide which preset graduates to MICRO-LIVE first (`close_sweep` is the highest-frequency candidate). Cap MICRO-LIVE sizing tightly (e.g. half the normal per-trade cap) and let the existing risk gate handle the rest — no new flag is required.
5. Reassess after ~30 live trades per graduated preset. If `Sim net EV (bps)` and the live realized cohort agree, scale; if they diverge, halt and re-audit.

If at any point the realized cohort shows negative net-EV across the four BTC/ETH × 5m/15m sub-buckets that meet `n >= MIN_OOS_TRADES`, the honest call is `DO NOT SCALE`.

## 8. Files created / modified

- `projects/polymarket/crusaderbot/domain/research/late_entry_realized_cohort.py` (new — read-only export)
- `projects/polymarket/crusaderbot/tests/test_late_entry_realized_cohort.py` (new — 10 safety/behaviour tests)
- `projects/polymarket/crusaderbot/reports/forge/late-entry-v3-edge-calibration.md` (this report)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `WORKTODO.md`, `CHANGELOG.md` (repo-truth sync)

## 9. Safety invariant statement

No live order, no real funds, no forced trade, no live-guard flip (`USE_REAL_CLOB` / `EXECUTION_PATH_VALIDATED` / `ENABLE_LIVE_TRADING` / `CAPITAL_MODE_CONFIRMED` untouched). Kelly stays 0.25 (never full); LIVE_MIN_ORDER_SHARES untouched; per-user balance isolation untouched; $5 live Auto-Trade start gate untouched; kill switch untouched. No strategy threshold or preset config changed. No deposit/withdraw / sweep / custody code changed. The new module is pure SELECT-only research (pinned by 10 tests including a source-import guard); it CANNOT emit an order intent or contact the CLOB / Bridge / Relayer / Gamma.

## 10. Validation evidence

- New `tests/test_late_entry_realized_cohort.py` → 10 passed (bucket math, MIN_OOS gate, simulated cost on YES + NO, query is SELECT-only + correctly scoped, source-pin: no live-path imports / no order calls / no guard reads).
- Full suite: `pytest projects/polymarket/crusaderbot/tests/` → 3659 passed, 15 skipped.
- `ruff check` + `python3 -m py_compile` clean on the new module and its test.
- Secret / mojibake / BOM scans clean on touched files.
- Branch verified `WARP/late-entry-v3-edge-calibration` (exact head, matches issue).

---

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: evidence-based calibration verdict + minimal read-only research export.
Not in Scope: strategy / risk / execution / capital / deposit / live-guard changes.
Suggested Next Step: WARP🔹CMD first-pass → R00T final-gate merge on CI green; operator flips `SCAN_SNAPSHOT_ENABLED=True` and starts the 14-day snapshot capture; the existing OOS harness is re-run once the substrate is populated.
