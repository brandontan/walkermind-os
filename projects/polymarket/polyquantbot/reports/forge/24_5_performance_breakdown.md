# 24.5 — Performance Breakdown Engine

## 1) What was built

- Implemented a robust closed-trade performance breakdown analyzer in `projects/polymarket/polyquantbot/monitoring/performance_breakdown.py`.
- Analyzer now groups closed trades by:
  - `market_type`
  - `signal`
  - `edge`
- Added per-group metrics:
  - `trades`
  - `wins`
  - `losses`
  - `win_rate`
  - `profit_factor`
  - `avg_win`
  - `avg_loss`
  - `expectancy`
  - `quality` (`LOW_SAMPLE` if trades < 10, otherwise `OK`)
- Added safe guards:
  - ignore malformed/missing-field trades
  - ignore non-closed trades
  - skip empty groups
  - no divide-by-zero crash (PF falls back to total profit when total loss is zero)
- Added Telegram command support for `/analysis` in `projects/polymarket/polyquantbot/telegram/command_handler.py` with grouped output blocks for MARKET / SIGNAL / EDGE.
- Integrated closed-trade compatibility in `projects/polymarket/polyquantbot/monitoring/performance_tracker.py` by defaulting status to `open` and updating to `closed` on close update.

## 2) Current system architecture

```text
DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING
                                             │
                                             └─ closed trade recorded in PerformanceTracker
                                                     │
                                                     └─ SnapshotEngine uses PerformanceBreakdown
                                                             │
                                                             └─ Telegram /analysis renders by_market/by_signal/by_edge
```

Key flow:
- open trade enters rolling tracker with `status=open`
- close event updates tracked trade (`status=closed`, realized `pnl`)
- snapshot builds grouped performance breakdown only from closed trades
- `/analysis` command reads snapshot payload and formats operator view

## 3) Files created / modified (full paths)

- `projects/polymarket/polyquantbot/monitoring/performance_breakdown.py` (MODIFIED)
- `projects/polymarket/polyquantbot/monitoring/performance_tracker.py` (MODIFIED)
- `projects/polymarket/polyquantbot/telegram/command_handler.py` (MODIFIED)
- `projects/polymarket/polyquantbot/reports/forge/24_5_performance_breakdown.md` (NEW)
- `PROJECT_STATE.md` (MODIFIED)

## 4) What is working

- Closed-trade-only filtering is active (`status == closed`).
- Grouping works for market/signal/edge buckets.
- Expectancy formula implemented and returned per group.
- Sample-size quality gate active (`LOW_SAMPLE` below 10).
- Safe PF logic for all-win groups (no division by zero).
- Missing trade fields are skipped safely.
- `/analysis` command now produces a structured performance breakdown message for Telegram.

## 5) Known issues

- `/analysis` depends on snapshot payload availability from the wired metrics source; if snapshot does not include `performance_breakdown`, command returns `NO DATA` sections safely.
- `docs/CLAUDE.md` is still referenced by process checklist but missing in repository.

## 6) What is next

- Run staging validation session on real closed-trade flow to verify operator-readability of MARKET/SIGNAL/EDGE breakdowns.
- Start strategy filtering using breakdown quality gates (`LOW_SAMPLE` handling + underperforming bucket suppression candidates).
- SENTINEL validation required before merge.
