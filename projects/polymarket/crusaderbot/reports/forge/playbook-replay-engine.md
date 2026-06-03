# WARP•FORGE — playbook-replay-engine (WARP-53 Phase-2c-3)

Role: WARP•FORGE (under the WARP•R00T PLAYBOOK epic, WARP-53)
Validation Tier: **STANDARD** (new research module; pure read-side, no trading wiring)
Claim Level: **FOUNDATION** (harness complete + tested; inert until snapshot data accrues)
Validation Target: the walk-forward replay units — metrics, fold splitter, bias detectors,
and the fail-soft `replay` orchestrator over `market_snapshots`.
Not in Scope: enabling data capture (`SCAN_SNAPSHOT_ENABLED`, operator); a CLI/job/dashboard
to run reports (follow-up); reconstructing full per-token order books (uses mid as the
settlement proxy from first/last snapshot); tuning thresholds.
Suggested Next Step: WARP🔹CMD review/merge → operator enables snapshot capture → once
`market_snapshots` has history, wire a scheduled/on-demand report + calibrate tunables.

---

## 1. What was built

Phase-2c-3 — the **validation half** of the backtest harness (blueprint §12.1), completing
the Phase-2c epic. It replays the historical market state captured in `market_snapshots`
(Phase-2c-2) through a strategy's *real* decision callable and scores the trades
out-of-sample — no parallel sim logic, so no sim/live drift.

`domain/research/replay.py` — three small **pure, testable** units plus an orchestrator:
- **`compute_metrics`** — win rate, EV/trade, **Sharpe**, **Sortino**, **profit factor**,
  **max drawdown**, average holding duration, over per-trade return fractions.
- **`walk_forward_split`** — expanding train→validate folds ordered by `entry_ts`, so a
  fold is only ever validated on trades *after* its training window (no look-ahead).
- **Bias detection** — `has_leakage` (entry at/after resolution = look-ahead) +
  `overfit_degradation` / `is_overfit` (in-sample vs OOS EV gap).
- **`trade_return`** — signed per-trade return for YES/NO (binary-market mechanics).
- **`replay(decide, …)`** — reads `market_snapshots`, groups by market (earliest snapshot =
  entry, latest = settlement proxy), runs the caller's `decide(row) -> (module, side)|None`,
  drops leaked trades, returns `{module: ReplayMetrics}`. **Inert until the table has data**
  → `{}`; fail-soft on every DB touch.

## 2. Current system architecture

No runtime/trading change. The replay engine is a pure read-side library over
`market_snapshots` + a caller-supplied decision callable (the same `evaluate_snapshot`-style
logic the live scan uses — the design contract that prevents sim/live drift). Nothing calls
it automatically yet; it is invoked on demand once data exists.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/domain/research/replay.py` — NEW
- `projects/polymarket/crusaderbot/tests/test_research_replay.py` — NEW (16 tests)
- `projects/polymarket/crusaderbot/reports/forge/playbook-replay-engine.md` — this report
- State: `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` · `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- **16 tests pass**; ruff + py_compile clean. Pinned: YES/NO/degenerate returns; metrics
  (win rate, EV, profit factor, drawdown, Sharpe/Sortino, all-loss); expanding walk-forward
  folds + too-few-trades guard; leakage + overfit detectors; and the orchestrator's
  empty-table-inert, fail-soft, trade-building, and skip (no-decision / single-snapshot) paths.

## 5. Known issues

- **Inert until `market_snapshots` accrues** — needs `SCAN_SNAPSHOT_ENABLED=true` (#1579) +
  time. With an empty table `replay` returns `{}` (by design).
- Settlement is the **last observed snapshot mid** as a proxy, not the on-chain resolution;
  good enough for relative scoring, refine to a `markets.resolved/winning_side` join when
  driving real capital decisions.
- No runner surface yet (CLI/job/dashboard) — invoked programmatically; a scheduled report
  is the natural follow-up once data exists.

## 6. What is next

- Operator: enable `SCAN_SNAPSHOT_ENABLED` so history accrues; then a report runner +
  threshold calibration (feeds the same tunables the Monte Carlo classifier uses).
- PLAYBOOK 2d Injury Alpha / 2e Public Fade — both need an external feed source (provider
  decision) before they can move off their stubs.

---

- Validation Tier: STANDARD
- Claim Level: FOUNDATION (harness complete; inert until data)
- Validation Target: metrics + walk-forward + bias detection + replay orchestrator
- Not in Scope: snapshot-capture enablement, report runner, full book reconstruction
- Suggested Next Step: WARP🔹CMD review/merge → operator enables capture → report runner
