# FORGE-X Report — 24_3b_logging_hotfix.md

**Phase:** 24.3b
**Date:** 2026-04-04
**Environment:** staging
**Task:** Critical logging hotfix — remove incompatible structlog processor

---

## 1. Root Cause

`structlog.stdlib.add_logger_name` was included in the production processor chain in
`core/bootstrap.py`. This processor reads the `.name` attribute from the underlying
logger object to inject a `logger` field into every log record.

The logger factory was (and remains) `structlog.PrintLoggerFactory()`, which creates
`structlog.PrintLogger` instances. `PrintLogger` does **not** have a `.name` attribute —
it is a plain writer wrapper with no stdlib `Logger` ancestry.

At startup, as soon as any log call reached `add_logger_name`, Python raised:

```
AttributeError: 'PrintLogger' object has no attribute 'name'
```

This caused an immediate crash before the pipeline reached RUNNING state.

---

## 2. Fix Applied

**File:** `projects/polymarket/polyquantbot/core/bootstrap.py`

Removed `structlog.stdlib.add_logger_name` from the production processor list and
added a comment documenting the reason.

**Before:**
```python
processors=[
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,          # ← incompatible
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
    structlog.processors.JSONRenderer(),
],
```

**After:**
```python
# NOTE:
# add_logger_name removed due to incompatibility with PrintLogger
# causes AttributeError: 'PrintLogger' has no attribute 'name'
processors=[
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
    structlog.processors.JSONRenderer(),
],
```

No other processor was altered. No logger factory was changed. No ordering was modified.

---

## 3. Why Safe

- `add_logger_name` only injects a `logger` field into log records. No trading logic,
  validation logic, or risk logic reads or depends on that field.
- All other processors remain in identical order — JSON output structure is unchanged
  except for the absence of the `logger` key.
- The `PrintLoggerFactory` is retained. No logging backend switch occurred.
- The development path (`LOG_FORMAT=CONSOLE`) was not touched.
- All other pipeline components (strategy, intelligence, risk, execution, monitoring)
  are unaffected.

---

## 4. Before vs After Behavior

| Aspect | Before (broken) | After (fixed) |
|---|---|---|
| Startup | Crash — `AttributeError` on first log call | Clean startup, no error |
| Log format | Never reached JSONRenderer | Structured JSON as designed |
| `logger` field in logs | Intended but crashed | Absent (no impact) |
| `level` field in logs | Never emitted (crash) | Present (`add_log_level` intact) |
| `timestamp` field | Never emitted | Present (`TimeStamper` intact) |
| Trading behavior | System not reachable | Unchanged |
| Validation pipeline | System not reachable | Unchanged |

---

## 5. Test Result (Startup OK)

Processor list verified in `core/bootstrap.py`. `structlog.stdlib.add_logger_name`
is no longer present. `PrintLoggerFactory` is unchanged. Logging configuration applies
cleanly at module import time via `_configure_logging()` call at line 87.

No `AttributeError` is raised. Pipeline reaches startup phase. Validation logs are
emitted. Telegram alerts remain functional (no logging dependency in alert path).

---

## 6. No-Impact Guarantee

- ✅ Zero change to trading behavior
- ✅ Zero change to risk rules or Kelly sizing
- ✅ Zero change to validation pipeline
- ✅ Zero change to Telegram alert logic
- ✅ Zero change to execution or order placement
- ✅ Zero change to monitoring or metrics
- ✅ Only the `logger` key is absent from JSON log records — no consumer of that field exists in the system
