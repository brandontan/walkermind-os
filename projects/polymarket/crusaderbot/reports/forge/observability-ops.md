# observability-ops

Validation Tier: **STANDARD**
Claim Level: **NARROW INTEGRATION**
Validation Target: Top-8 stdlib `logging` modules migrated to `structlog` keyword-arg API; Sentry + healthcheck surface audited (read-only).
Not in Scope: Bridging structlog → stdlib so `caplog` and Sentry breadcrumbs capture structlog events; migrating the long tail of remaining stdlib `logging` modules; new healthcheck dependencies; Sentry runbook.

## 1. What was built

End-to-end migration of the top-8 stdlib-`logging` modules in the runtime to `structlog`:

- `users.py` (10 calls) — chunk 1
- `domain/risk/kill_switch_exec.py` (11) — chunk 1
- `integrations/polymarket.py` (16) — chunk 1
- `bot/handlers/admin.py` (16) — chunk 1
- `domain/strategy/strategies/late_entry_v3.py` (16) — chunk 2
- `scheduler.py` (22) — chunk 2
- `domain/execution/lifecycle.py` (21) — chunk 2
- `domain/execution/exit_watcher.py` (17) — chunk 2

Total: **129 logger call sites** rewritten across 8 modules. `monitoring/logging.py` processor chain extended with `structlog.processors.format_exc_info` so `log.exception()` calls serialise the traceback correctly under the JSON renderer.

Conversion shape (applied uniformly):
- `logger.info("msg %s %s", a, b)` → `log.info("msg", key1=a, key2=b)`
- `logger.error(..., exc_info=True)` inside `except` → `log.exception(...)`
- `extra={"k": v}` dicts inlined as kwargs
- Multi-line `%s` format strings flattened into structured kwargs

Sentry + healthcheck audit (read-only, no code change):
- Sentry init exists at `monitoring/sentry.py`. DSN-gated, FastAPI + Starlette integrations wired, env / release / traces-sample-rate read from `os.environ` directly so a partially-configured env never blocks boot. `send_default_pii=False` — PII safe by default. Boot init at `main.py:lifespan` runs before settings validation.
- Healthchecks at `api/health.py`: `/health` runs `check_database`, `check_telegram`, `check_alchemy_rpc`, `check_alchemy_ws` (full WS handshake + `eth_blockNumber` RPC since M-3 alchemy-ws-handshake lane). `/ready` retained for backward-compat. Rate-limit middleware exempts both paths.
- Outcome: no hardening needed in this lane. Sentry + health are production-ready as-is for closed beta.

## 2. Current system architecture

```
DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING
                                                       │
                                                       ├── structlog (8 modules)
                                                       ├── stdlib logging (long tail)
                                                       ├── Sentry (DSN-gated)
                                                       └── /health + /ready
```

`monitoring/logging.py` configures both renderers (stdlib `_JsonFormatter` for legacy callers + structlog `JSONRenderer` for migrated modules); both emit a single JSON line per record on stdout for Fly log aggregation. Migrated modules use `log = structlog.get_logger(__name__)`; remaining modules continue to use `logger = logging.getLogger(__name__)` and remain captured by `_JsonFormatter`.

## 3. Files created / modified (full repo-root paths)

Chunk 1 (merged #1428):
- projects/polymarket/crusaderbot/monitoring/logging.py — `format_exc_info` added to structlog processor chain
- projects/polymarket/crusaderbot/users.py
- projects/polymarket/crusaderbot/domain/risk/kill_switch_exec.py
- projects/polymarket/crusaderbot/integrations/polymarket.py
- projects/polymarket/crusaderbot/bot/handlers/admin.py

Chunk 2 (merged #1429):
- projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py
- projects/polymarket/crusaderbot/scheduler.py
- projects/polymarket/crusaderbot/domain/execution/lifecycle.py
- projects/polymarket/crusaderbot/domain/execution/exit_watcher.py
- projects/polymarket/crusaderbot/tests/test_warp54_closed_beta_hardening.py — `test_log_resumed_open_positions_emits_count` migrated from `caplog` to `structlog.testing.capture_logs`

Chunk 3 (this lane):
- projects/polymarket/crusaderbot/reports/forge/observability-ops.md
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md
- projects/polymarket/crusaderbot/state/CHANGELOG.md

## 4. What is working

- All 129 migrated call sites compile clean (`py_compile`).
- Full local test suite: **1912 passed / 6 skipped / 0 failures**.
- CI green on both chunk PRs (Lint + Test + CodeRabbit clean).
- structlog calls emit JSON records with structured kwargs visible alongside the message (verified via `capture_logs()` in the migrated regression test).
- `log.exception()` traceback serialisation now functions (was previously silent under structlog because `format_exc_info` was missing from the processor chain).
- Sentry: DSN-gated init, never crashes boot, FastAPI + Starlette captured automatically.
- /health + /ready endpoints cover all four runtime dependencies (DB, Telegram, Alchemy RPC, Alchemy WS).

## 5. Known issues

- **Sentry breadcrumb gap for structlog**: structlog's `make_filtering_bound_logger` does not flow through stdlib `logging`, so Sentry's stdlib `LoggingIntegration` does not capture WARN/ERROR breadcrumbs emitted via `log.error(...)` from migrated modules. Sentry still captures unhandled exceptions via the FastAPI/Starlette integrations, so unhandled errors are still reported — but a manually-logged `log.error(...)` that does not raise will not appear in Sentry. Closing this requires switching to `structlog.stdlib.LoggerFactory` + `ProcessorFormatter` bridge. **Deferred**, low risk for closed beta (the migrated paths catch their own exceptions and FastAPI integration still covers route-level errors).
- **Long tail of stdlib loggers**: ~30 remaining modules still call `logging.getLogger(__name__)`. They keep working under the JSON formatter; they are out of scope for M-3 ("top-8") and have no current bug pressure.
- **Reserved-kwarg footgun**: structlog reserves `event` as the first positional arg (the log message). `log.info("msg", event=...)` raises `TypeError`. Caught in chunk 2 CI (commit `0c766f3` fix) — `event=event` → `payload=event` in two `lifecycle.handle_ws_fill` drop logs.

## 6. What is next

- Axis #4 onboarding-ux (STANDARD): first-run UX polish, sign-up flow, empty states, disclaimers, ToS/Privacy stubs.
- Then Axis #1 multi-tenant safety (MAJOR), Axis #3 live-activation flow (MAJOR), Axis #7 public-readiness audit.

## Suggested Next Step

WARP🔹CMD review + merge of this lane, then start Axis #4 `WARP/ROOT-onboarding-ux`.
