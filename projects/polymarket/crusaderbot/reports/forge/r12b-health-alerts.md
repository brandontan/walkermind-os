# WARP•FORGE — R12b Health Alerts

**Branch:** WARP/CRUSADERBOT-R12B-HEALTH-ALERTS
**Date:** 2026-05-05 05:00 Asia/Jakarta
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** observability layer (health endpoint dependency probes,
operator alert dispatcher, startup env validation, JSON request logging)
**Not in Scope:** trading / execution / risk paths, Redis dependency, schema
changes, PTB command surface, secret value logging.

---

## 1. What was built

End-to-end observability layer for CrusaderBot:

- **Multi-dependency `/health` probe** — `GET /health` now reports the status
  of database, Telegram, Alchemy RPC, and Alchemy WebSocket dependencies in a
  fixed JSON shape. Each check has a hard 3-second timeout enforced by
  `asyncio.wait_for`; the endpoint never hangs.
- **Operator-alert dispatcher** — sends plain-text Telegram alerts to
  `OPERATOR_CHAT_ID` for: 2+ consecutive `/health` failures (threshold-gated),
  Fly.io machine restart on every cold start, and any required dependency
  unreachable at boot. 5-minute cooldown per (alert type, key) tuple.
- **Startup env validation** — `validate_required_env()` logs an ERROR line
  per missing required variable (key name only — values never logged) and
  returns the missing-key list to the lifespan hook so the alert dispatcher
  pages the operator. The process is allowed to continue so `/health`
  surfaces the degraded state.
- **JSON structured logging baseline** — replaces the previous structlog
  `ConsoleRenderer` with a JSON formatter on the stdlib root logger. Adds a
  `RequestLogMiddleware` that emits one structured line per HTTP request with
  `method`, `path`, `status_code`, `duration_ms`. Errors in the request
  pipeline are logged at ERROR with `exc_type` and re-raised.
- **Fly.io probe tuning** — `fly.toml` `http_checks` now use `interval=10s`
  and `grace_period=10s` per task spec; `path` already pointed at `/health`.

## 2. Current system architecture

```
   ┌────────────────────────────────────────────────────────────┐
   │  FastAPI  (main.py)                                        │
   │   ├── add_middleware(RequestLogMiddleware) ─► JSON log line │
   │   └── lifespan ─► validate_required_env()                   │
   │                  ├─► alert_startup(restart_detected=True)   │
   │                  └─► run_health_checks() at boot            │
   │                       └─► alert_dependency_unreachable(*)   │
   │                                                            │
   │   GET /health                                              │
   │     └─► monitoring.health.run_health_checks()              │
   │           ├─► check_database()    (db_ping, asyncpg)       │
   │           ├─► check_telegram()    (bot.get_me)             │
   │           ├─► check_alchemy_rpc() (httpx eth_blockNumber)  │
   │           └─► check_alchemy_ws()  (asyncio.open_connection)│
   │     └─► monitoring.alerts.record_health_result(result)     │
   │           ├─ counter ≥ 2 → alert_health_degraded()         │
   │           └─ cooldown 5 min  → suppress duplicate          │
   └────────────────────────────────────────────────────────────┘
```

Trading and execution paths are explicitly NOT instrumented from this layer
per the task spec. Risk constants and Kelly sizing are unchanged.

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/monitoring/__init__.py`
- `projects/polymarket/crusaderbot/monitoring/health.py`
- `projects/polymarket/crusaderbot/monitoring/alerts.py`
- `projects/polymarket/crusaderbot/monitoring/logging.py`
- `projects/polymarket/crusaderbot/tests/test_health.py`

Modified:
- `projects/polymarket/crusaderbot/api/health.py` — route now delegates to
  `monitoring.health.run_health_checks`, returns the documented JSON shape,
  and feeds `monitoring.alerts.record_health_result` for threshold-gated
  paging. `/ready` mirrors the `ready` boolean for legacy probes.
- `projects/polymarket/crusaderbot/config.py` — added `REQUIRED_ENV_VARS`
  tuple, `validate_required_env()` helper (key-only logging),
  `ALCHEMY_POLYGON_RPC_URL` and `ALCHEMY_POLYGON_WS_URL` as `Optional[str]`
  fields (the latter was already referenced in `services/deposit_watcher.py`
  but had no Settings declaration — now it does).
- `projects/polymarket/crusaderbot/main.py` — JSON logging baseline replaces
  the `ConsoleRenderer` setup; `RequestLogMiddleware` registered on the
  FastAPI app; lifespan now runs env validation, fires startup alerts, and
  pages on any boot-time dependency failure. Removed unused `sys` and
  `structlog` imports from `main.py` since `configure_json_logging` owns
  the renderer now.
- `projects/polymarket/crusaderbot/fly.toml` — `interval` 15s → 10s,
  `grace_period` 30s → 10s. `path` already `/health`, `timeout` already 5s.

## 4. What is working

- `pytest projects/polymarket/crusaderbot/tests/` — 10 passed, 0 failed
  (8 new in `test_health.py`, 2 existing in `test_smoke.py`).
- `python -m py_compile` clean for every file touched.
- `validate_required_env()` smoke check with a stub environment returns the
  expected missing-key list and logs key names only (verified — no values in
  the log output).
- `/health` JSON shape matches the spec exactly: top-level keys
  `status`, `service`, `checks`, `ready`; `checks` keys
  `database`, `telegram`, `alchemy_rpc`, `alchemy_ws`; no Redis key.
- All checks complete within `CHECK_TIMEOUT_SECONDS=3.0`. The hang test
  (`test_check_does_not_hang_past_timeout`) confirms the timeout is enforced
  even when the underlying coroutine sleeps indefinitely.
- Alert dispatcher honours both gates: first failure does NOT page;
  second consecutive failure pages once; subsequent failures inside the
  5-minute window are suppressed; a recovery (`status: ok`) resets the
  counter so the next single failure does NOT page again.
- `app.add_middleware(RequestLogMiddleware)` is wired before
  `include_router(...)` so every HTTP request — including the `/health`
  probe — is logged in JSON with `duration_ms`.

## 5. Known issues

- Local-environment cryptography binding panic (PyO3) is unrelated to this
  lane — fixed in this dev box by upgrading `cryptography` so the test suite
  could import `python-telegram-bot`. Production / CI environments use
  pinned wheels and are not affected.
- `check_alchemy_ws()` does a TCP-level reachability probe rather than a
  full WebSocket handshake, intentionally to avoid pulling a `websockets`
  dependency that is not currently in `pyproject.toml`. This still surfaces
  DNS / SSL / firewall outages, which is the operator-relevant failure
  mode. A full handshake check is a follow-up if needed.
- `services/deposit_watcher.py` already referenced
  `settings.ALCHEMY_POLYGON_WS_URL` before this lane; the field is now
  declared as `Optional[str]`. No behavioural change to the watcher.

## 6. What is next

- **R12c — Auto-Close / Take-Profit (MAJOR)** is the next gated lane and
  WILL require WARP•SENTINEL.
- Suggested follow-up (separate lane): wire a periodic background task that
  calls `run_health_checks()` every N seconds so the alert dispatcher fires
  even in low-traffic windows where `/health` is only hit by Fly.io probes.

---

**Suggested Next Step:**
WARP🔹CMD review — STANDARD tier, no SENTINEL required.
