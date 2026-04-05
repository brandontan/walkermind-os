# 24.5 — Performance Breakdown Engine

## 1) What was built

- Added `PerformanceBreakdown` engine to compute grouped performance by:
  - market type
  - signal strength
  - edge classification
- Implemented grouped metrics:
  - `trades`
  - `win_rate = wins / total`
  - `profit_factor = total_profit / total_loss` (safe fallback: when `total_loss == 0`, PF = `total_profit`)
- Integrated breakdown payload into periodic validation snapshots under:
  - `performance_breakdown.by_market`
  - `performance_breakdown.by_signal`
  - `performance_breakdown.by_edge`
- Added trading-loop data hook so tracked trades include:
  - `pnl`
  - `result`
  - `market_type`
  - `signal`
  - `edge`
- Preserved no-crash behavior:
  - no trades → empty structure
  - conversion errors → safe defaults

## 2) Current system architecture

```text
DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING
                                                │
                                                ├─ PerformanceTracker (rolling trades)
                                                │    └─ stores pnl/result/market_type/signal/edge
                                                │
                                                └─ SnapshotEngine.build_snapshot(...)
                                                     └─ PerformanceBreakdown.analyze(trades)
                                                          ├─ by_market (WR/PF/trades)
                                                          ├─ by_signal (WR/PF/trades)
                                                          └─ by_edge   (WR/PF/trades)
```

RISK remains before EXECUTION; monitoring receives post-execution events and snapshot analytics.

## 3) Files created / modified (full paths)

- `projects/polymarket/polyquantbot/monitoring/performance_breakdown.py` (NEW)
- `projects/polymarket/polyquantbot/monitoring/snapshot_engine.py` (MODIFIED)
- `projects/polymarket/polyquantbot/core/pipeline/trading_loop.py` (MODIFIED)
- `projects/polymarket/polyquantbot/reports/forge/24_5_performance_breakdown.md` (NEW)
- `PROJECT_STATE.md` (MODIFIED)

## 4) What is working

- Breakdown by market type works (`by_market`).
- Breakdown by signal strength works (`by_signal`).
- Breakdown by edge class works (`by_edge`).
- Snapshot payload now includes `performance_breakdown`.
- Safe PF and WR calculations are active.
- Empty trade input returns:
  - `{"by_market": {}, "by_signal": {}, "by_edge": {}}`
- Runtime remains defensive (no exception propagation from snapshot builder).

## 5) Known issues

- `/analysis` Telegram command output is not yet wired in `telegram/command_handler.py`; current delivery path is periodic `system_snapshot` payload/log output.
- `docs/CLAUDE.md` is still referenced by process checklist but missing from repository.

## 6) What is next

- Run staging validation to collect real grouped WR/PF distributions over live paper traffic.
- Add `/analysis` command wiring in Telegram command path for operator-friendly direct view.
- Start strategy optimization cycle using lowest-PF cohorts first.
- Request SENTINEL validation before merge.
