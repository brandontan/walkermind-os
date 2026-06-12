# WARP•R00T Report — health-probe-noise

Last Updated : 2026-06-12 15:35 UTC
Project      : CrusaderBot
Project Root : projects/polymarket/crusaderbot
Branch       : warp/root-health-probe-noise
Tier         : STANDARD
Claim Level  : NARROW INTEGRATION
Source       : Sentry (vurtnex/dawn-snowflake-1729) — "health check failed: name=telegram type=NetworkError" (~5064 events/14d) + "/health TimeoutError" (62/1h)

## Problem found
`/health` sub-check failures flooded Sentry's error stream — ~5064 `health check failed: name=telegram ...` events over 14 days (62/hour), with `users=0` and zero customer impact. The bot kept trading throughout; a slow/flaky Telegram `getMe` (or RPC) probe was paging as an ERROR every poll.

## Root cause
`monitoring/health.py::_with_timeout` logged EVERY probe exception at `logger.error` (line 89). Sentry's default `LoggingIntegration` has `event_level=ERROR`, so each transient `httpx.ConnectError`/`ReadError` from a NON-blocking probe became a Sentry event. But per the module's own aggregation rules, only a **database** failure drives `status='down'`/`ready=False`; telegram / alchemy_rpc / alchemy_ws failures merely set `status='degraded'` (`ready=True`). So a non-blocking probe blip was being escalated to operator-critical severity.

## Risk level
LOW (observability/alert-fatigue). No runtime/capital impact — purely the severity at which a non-blocking probe failure is logged.

## Technical impact
Sentry error volume dominated by non-actionable health noise, burying real errors and consuming quota. Operators still get paged for genuine outages via `monitoring/alerts.py` (consecutive-failure threshold + cooldown), which is unchanged.

## Recommended solution (implemented)
Severity now follows criticality:
- `_with_timeout` gains a `critical: bool = True` param. On a probe exception it logs `logger.error` when `critical` else `logger.warning`.
- `run_health_checks`: `database` stays `critical=True` (ERROR → Sentry event, since it drives `ready=False`); `telegram` / `alchemy_rpc` / `alchemy_ws` are `critical=False` (WARNING → breadcrumb, not an error event).
- The public `/health` payload, the timeout branch, the URL-scrubbing, and the alert-threshold path are all unchanged. A real DB outage still pages at ERROR.

## Files affected
- projects/polymarket/crusaderbot/monitoring/health.py (severity routing)
- projects/polymarket/crusaderbot/tests/test_health.py (+2 severity tests; existing leak test now captures at WARNING since alchemy_rpc is non-critical)
- state/PROJECT_STATE.md, state/CHANGELOG.md (repo-truth sync)

## Validation performed
- `pytest tests/test_health.py` → 44 passed; monitoring/ops/alert sweep → 223 passed, 1 skipped.
- ruff + py_compile clean. UTF-8/no-BOM verified.

## Note (not fixed here)
The separate `"/health TimeoutError"` issue (62/1h, transaction `/health`) is not emitted by `_with_timeout` (its `asyncio.TimeoutError` branch logs nothing) — it is most likely Fly.io's external `http_check` probe timing out or a tracing span, and confirming the exact source needs the live Sentry event stacktrace. Out of scope for this severity fix.

## Inviolable invariants — confirmed clean
Logging-severity change only; no risk-constant / Kelly change; no live-guard flip; no secrets (URL scrubbing preserved); asyncio only; no real fund movement.
