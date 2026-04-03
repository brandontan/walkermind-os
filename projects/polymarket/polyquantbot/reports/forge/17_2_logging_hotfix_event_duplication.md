# 17_2 — Logging Hotfix: Event Keyword Duplication

## 1. What Was Built

Fixed a fatal logging crash caused by duplicate `event=` keyword arguments in structlog
calls. structlog maps the first positional argument of every log call to the internal
`event` key. When a caller also passed `event=` as an explicit keyword argument, Python
raised:

```
TypeError: got multiple values for keyword argument 'event'
```

This prevented the Railway container from booting and caused a restart loop.

---

## 2. Current System Architecture

No architectural changes. The fix is purely a correction of incorrect log call syntax across
three files, plus a defensive guard in the shared `core/logging/logger.py` helper module.

Pipeline unchanged:

```
DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING
```

---

## 3. Files Created / Modified

| Action   | Path                                                                           |
|----------|--------------------------------------------------------------------------------|
| Modified | `projects/polymarket/polyquantbot/main.py`                                     |
| Modified | `projects/polymarket/polyquantbot/telegram/handlers/callback_router.py`        |
| Modified | `projects/polymarket/polyquantbot/core/pipeline/pipeline_runner.py`            |
| Modified | `projects/polymarket/polyquantbot/core/logging/logger.py`                      |
| Created  | `projects/polymarket/polyquantbot/reports/forge/17_2_logging_hotfix_event_duplication.md` |

### Changes per file

**main.py (line 154)**
```python
# BEFORE (crashes — duplicate keyword 'event')
log.info("metrics_initialized", event="metrics_initialized", initialized=True)

# AFTER (correct — first positional arg IS the event)
log.info("metrics_initialized", initialized=True)
```

**telegram/handlers/callback_router.py (lines 363–368)**
```python
# BEFORE (crashes — duplicate keyword 'event')
log.info("strategy_toggle", event="strategy_toggle", strategy=strategy_name, active=new_state)

# AFTER (correct)
log.info("strategy_toggle", strategy=strategy_name, active=new_state)
```

**core/pipeline/pipeline_runner.py (lines 999–1003)**
```python
# BEFORE (crashes — local variable 'event' clashes with structlog's internal 'event' key)
log.warning("phase10_telegram_notify_failed", event=event, error=str(exc))

# AFTER (renamed kwarg to preserve the data without conflict)
log.warning("phase10_telegram_notify_failed", pipeline_event=event, error=str(exc))
```

**core/logging/logger.py**
- Added `_assert_no_event_kwarg(**kwargs)` guard function.
- Wired the guard into `log_market_parse_warning` and `log_invalid_market` (the two
  publicly exported helpers) to raise a clear `AssertionError` at call-time if a caller
  inadvertently passes `event=` through `**extra`.

---

## 4. What Is Working

- All three offending log calls are fixed.
- System boots without `TypeError: got multiple values for keyword argument 'event'`.
- Structured JSON logs remain correct — event names are still the first positional arg.
- The `pipeline_event` field in `pipeline_runner.py` preserves the pipeline event type
  (e.g. `"execution_failure"`) in the log record without shadowing structlog internals.
- Defensive guard in `core/logging/logger.py` prevents regressions in future helper usage.

---

## 5. Known Issues

None introduced by this change. Pre-existing issues are unchanged.

---

## 6. What Is Next

- SENTINEL validation pass on Railway deployment to confirm clean boot.
- Monitor logs for `pipeline_event` field (renamed from `event`) in alerting/dashboards
  and update any log-aggregation queries if needed.
