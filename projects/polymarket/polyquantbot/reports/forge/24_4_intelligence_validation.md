# 24.4 — Intelligence + Validation UI Visibility

## 1) What was built

- Extended Telegram PORTFOLIO formatter to expose AI explainability fields in ACTIVE POSITION (`CONF`, `EDGE`, `SIGNAL`, `REASON`) using safe `N/A` fallback behavior.
- Extended Telegram HOME formatter with a new VALIDATION block under INTELLIGENCE:
  - `STATUS`
  - `TRADES` (shown as `count/30`)
  - `WR`
  - `PF`
- Added validation snapshot mapping logic in the trading loop UI mapper with explicit status classification:
  - `<30 trades` → `WARMING`
  - criteria met → `PASS`
  - below threshold → `CRITICAL`
- Kept all mappings crash-safe for missing/invalid values.

## 2) Current system architecture

UI mapping architecture after this increment:

```text
command input (/home | /portfolio)
        ↓
core/pipeline/trading_loop.py
  - map_ui_data(...)
  - build_portfolio_intelligence(...)
  - build_validation_snapshot(...)
  - classify_edge(...)
  - classify_strength(...)
  - classify_validation_status(...)
        ↓
utils/ui_formatter.py
  - build_home()      -> includes VALIDATION section
  - build_portfolio() -> includes CONF/EDGE/SIGNAL/REASON
        ↓
formatted Telegram response
```

Pipeline order remains unchanged and compliant:

`DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING`

## 3) Files created / modified (full paths)

- `projects/polymarket/polyquantbot/utils/ui_formatter.py` (MODIFIED)
- `projects/polymarket/polyquantbot/core/pipeline/trading_loop.py` (MODIFIED)
- `projects/polymarket/polyquantbot/reports/forge/24_4_intelligence_validation.md` (NEW)
- `PROJECT_STATE.md` (MODIFIED)

## 4) What is working

- `/portfolio` rendering now shows explainability fields: `CONF`, `EDGE`, `SIGNAL`, `REASON`.
- Edge classification rules are active:
  - `ev < 0.01` → `LOW`
  - `0.01–0.05` → `MEDIUM`
  - `>0.05` → `HIGH`
- Signal strength rules are active:
  - `prob < 0.55` → `WEAK`
  - `0.55–0.65` → `MODERATE`
  - `>0.65` → `STRONG`
- `/home` rendering now includes VALIDATION visibility block with status/trade progress/WR/PF.
- Validation status classification works with warmup gate and thresholds.
- Missing values are handled with `N/A` and do not crash formatting.

## 5) Known issues

- `docs/CLAUDE.md` is referenced by process checklist but missing in repository.
- Local test environment lacks async pytest plugin configuration, so a subset of async tests cannot run in this container without additional test deps/plugin setup.

## 6) What is next

- Run staging validation session and collect operator readability feedback for HOME/PORTFOLIO telemetry.
- Start Phase 24.4 performance analysis using validation snapshots and runtime WR/PF behavior.
- Request SENTINEL validation before merge.
