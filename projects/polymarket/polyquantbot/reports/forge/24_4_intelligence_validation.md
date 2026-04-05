# 24.4 — Intelligence + Validation UI Visibility

## 1) What was built

- Extended `/portfolio` UI output to expose active intelligence context directly in Telegram:
  - `CONF` (confidence from model probability)
  - `EDGE` (EV class)
  - `SIGNAL` (probability strength class)
  - `REASON` (trade rationale, safe fallback)
- Extended `/home` UI output with a dedicated validation block directly below intelligence:
  - `STATUS`
  - `TRADES` (x/30)
  - `WR`
  - `PF`
- Added mapping and classifier logic in trading loop UI data mapping:
  - `classify_edge(ev)`
  - `classify_strength(probability)`
  - `resolve_validation_status(trades_count, winrate, profit_factor)`
- Added safe defaults (`"N/A"`) for missing/unparseable intelligence and validation fields to ensure no crash/no UI break behavior.

## 2) Current system architecture

Telegram UI mapping flow now includes derived intelligence + validation states:

```text
command input (/home|/portfolio|/wallet|/performance)
        ↓
core/pipeline/trading_loop.py
  - map_ui_data(command, source)
    - classify_edge(ev)
    - classify_strength(probability)
    - resolve_validation_status(...)
        ↓
utils/ui_formatter.py
  - build_home()      + VALIDATION block
  - build_portfolio() + ACTIVE POSITION intelligence fields
        ↓
formatted Telegram text output
```

Pipeline order remains unchanged and compliant:

`DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING`

## 3) Files created / modified (full paths)

- `projects/polymarket/polyquantbot/utils/ui_formatter.py` (MODIFIED)
- `projects/polymarket/polyquantbot/core/pipeline/trading_loop.py` (MODIFIED)
- `projects/polymarket/polyquantbot/reports/forge/24_4_intelligence_validation.md` (NEW)
- `PROJECT_STATE.md` (MODIFIED)

## 4) What is working

- `/portfolio` now shows `CONF / EDGE / SIGNAL / REASON` in `📌 ACTIVE POSITION`.
- `/home` now shows `🧪 VALIDATION` with status + trade count + WR + PF.
- Classification behavior implemented:
  - EDGE: LOW / MEDIUM / HIGH from EV thresholds
  - SIGNAL: WEAK / MODERATE / STRONG from probability thresholds
- Validation status behavior implemented:
  - `<30 trades` → `WARMING`
  - Meets thresholds (`WR >= 0.70` and `PF >= 1.50`) → `PASS`
  - Otherwise → `CRITICAL`
- Missing/invalid fields are safely rendered as `N/A` (no formatting exceptions).

## 5) Known issues

- `docs/CLAUDE.md` is referenced in process checklist but still absent in repository.
- End-to-end Telegram visual confirmation depends on active staging bot session and operator-triggered `/home` and `/portfolio` commands.

## 6) What is next

- Continue staging validation run to collect WR/PF trend reliability and confidence-to-outcome alignment.
- Run performance analysis on telemetry readability under active market load.
- SENTINEL validation required for intelligence + validation visibility before merge.
