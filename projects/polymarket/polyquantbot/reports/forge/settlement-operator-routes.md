# settlement-operator-routes — Priority 7 Forge Report

## Validation Metadata

- Branch: WARP/settlement-operator-routes
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target: `server/services/settlement_operator_service.py`, `server/api/settlement_operator_routes.py` — HTTP operator console exposure for settlement status, retry status, failed batches, and admin intervention (§47 Gate 1b)
- Not in Scope: Live DB integration test against real PostgreSQL, Telegram wiring (Gate 1c), batch result persistence (batch persistence lane deferred)
- Suggested Next Step: WARP🔹CMD review before merge; Gate 1c Telegram wiring after this is merged

---

## 1. What Was Built

Gate 1b exposes the `OperatorConsole` (built in PR #777) via HTTP. The `OperatorConsole` is data-injected — it needs data loaded from `SettlementPersistence` before its methods can be called. The service layer bridges these two components.

**`SettlementOperatorService`** (`server/services/settlement_operator_service.py`):
- Constructor: takes `persistence: SettlementPersistence` + `console: OperatorConsole`
- `get_settlement_status(workflow_id)` → loads events via `persistence.load_events_for_workflow()`, loads retry history via `persistence.load_retry_history()`, reconstructs `SettlementWorkflowResult` from events via `_build_result_from_events()`, calls `console.get_settlement_status()` → `SettlementStatusView`
- `get_retry_status(workflow_id)` → loads retry history, calls `console.get_retry_status()` with default `RetryPolicy()` → `RetryStatusView`
- `get_failed_batches()` → calls `console.get_failed_batches([])` (batch results not persisted in current persistence layer; returns empty list)
- `apply_admin_intervention(intervention)` → loads events, reconstructs result, calls `console.apply_admin_intervention()`; returns `None` when workflow has no events (404 at route layer)
- `_build_result_from_events()`: maps latest event type to workflow status string; infers `success`, `completed_at`, `blocked_reason` from event payload
- All methods log structured events via `structlog`; exceptions propagate (no silent swallow)

**`build_settlement_operator_router()`** (`server/api/settlement_operator_routes.py`):
- 4 routes under `/admin/settlement/` — mirrors `build_orchestration_router()` pattern exactly
- Auth: `SETTLEMENT_ADMIN_TOKEN` env var via `X-Settlement-Admin-Token` header; `_check_admin()` raises 403 on missing/wrong token
- Service access: `getattr(request.app.state, "settlement_operator_service", None)` → 503 when not wired
- `AdminInterventionBody` Pydantic model for POST body (maps to frozen `AdminInterventionRequest` dataclass)
- JSON serialization uses FastAPI `jsonable_encoder(...)` for dataclasses and datetime fields
- Mutation route (`POST /intervene`): returns 404 when service returns `None` (workflow not found); exceptions → 500

**`server/main.py` wiring** (lifespan, after P6C orchestration block):
- `SettlementPersistence(db=state.db_client)` instantiated
- `SettlementAlertPolicy()` + `OperatorConsole(alert_policy=...)` instantiated
- `SettlementOperatorService(persistence=..., console=...)` → `app.state.settlement_operator_service`
- `build_settlement_operator_router()` registered via `app.include_router()`

---

## 2. Current System Architecture

```
[Telegram] (Gate 1c — not yet built)
        │
        ▼
[FastAPI] /admin/settlement/*  — settlement_operator_routes.py
        │  auth: SETTLEMENT_ADMIN_TOKEN / X-Settlement-Admin-Token
        │  503 when not wired; 403 on auth fail; 404 workflow not found; 500 on exception
        ▼
SettlementOperatorService
        │
        ├── SettlementPersistence.load_events_for_workflow()
        │       → list[SettlementEvent]  (from settlement_events table)
        │
        ├── SettlementPersistence.load_retry_history()
        │       → list[RetryAttemptRecord]  (from settlement_retry_history table)
        │
        ├── _build_result_from_events()
        │       → SettlementWorkflowResult | None
        │
        └── OperatorConsole
                ├── get_settlement_status()  → SettlementStatusView
                ├── get_retry_status()       → RetryStatusView
                ├── get_failed_batches()     → Sequence[FailedBatchView]  (always [] — batch persistence deferred)
                └── apply_admin_intervention() → AdminInterventionResult

[PostgreSQL]
  settlement_events              — event log (DDL: migration 001, database.py)
  settlement_retry_history       — retry attempts (DDL: migration 001, database.py)
  settlement_reconciliation_results — recon state (DDL: migration 001, database.py)
```

---

## 3. Files Created / Modified (full repo-root paths)

**Created:**
```
projects/polymarket/polyquantbot/server/services/settlement_operator_service.py
projects/polymarket/polyquantbot/server/api/settlement_operator_routes.py
projects/polymarket/polyquantbot/tests/test_settlement_p7_operator_routes.py
projects/polymarket/polyquantbot/reports/forge/settlement-operator-routes.md
```

**Modified:**
```
projects/polymarket/polyquantbot/server/main.py
projects/polymarket/polyquantbot/state/PROJECT_STATE.md
projects/polymarket/polyquantbot/state/WORKTODO.md
projects/polymarket/polyquantbot/state/CHANGELOG.md
```

---

## 4. What Is Working

- All 9 Gate 1b tests pass: ST-39..ST-47 (9/9)
- `GET /admin/settlement/status/{workflow_id}` → 403 (no/wrong token), 503 (not wired), 200 + SettlementStatusView JSON shape
- `GET /admin/settlement/retry/{workflow_id}` → 403 (no/wrong token), 503 (not wired), 200 + RetryStatusView JSON shape
- `GET /admin/settlement/failed-batches` → 200 + list (empty until batch persistence built)
- `POST /admin/settlement/intervene` → 200 + AdminInterventionResult; 404 when workflow not found; 403 on bad token; 503 not wired
- `jsonable_encoder(...)` correctly converts dataclasses and `datetime` fields to JSON-safe output
- `SettlementOperatorService` correctly propagates exceptions (no silent failures)
- `_build_result_from_events()`: returns `None` for empty event list (triggers NOT_FOUND console path); maps all 7 event types to status strings
- `server/main.py`: settlement operator service wired in lifespan with correct dependency order (after DB connects); router registered

---

## 5. Known Issues

- `get_failed_batches()` always returns `[]` — batch results (`SettlementBatchResult`) are not persisted in the current persistence layer; a dedicated batch persistence lane would be required to populate this endpoint
- `apply_admin_intervention()` does not persist the intervention record — per the existing `OperatorConsole` known issue (documented in PROJECT_STATE.md): service layer callers must handle persistence explicitly; intervention effect is in-memory/logging only
- `SettlementOperatorService` uses `SettlementPersistence.load_events_for_workflow()` which returns `[]` on DB error (fail-safe read), meaning a DB failure silently appears as workflow NOT_FOUND rather than a 500; this is the existing persistence contract and is acceptable for operator console reads

---

## 6. What Is Next

- Gate 1c: Telegram wiring for settlement status commands (`/settlement_status`, `/retry_status`, `/failed_batches`) on branch `WARP/settlement-telegram-wiring` — depends on this PR being merged
- After Gate 1c merged: all three P7 deferred items (§47, §48, settlement DDL) will be complete
- Priority 8: Production-capital readiness gating (requires full SENTINEL MAJOR sweep after P8 lanes built)

---

## Metadata

- **Validation Tier:** STANDARD
- **Claim Level:** NARROW INTEGRATION (service + routes over existing persistence/console; no new infra)
- **Validation Target:** §47 HTTP operator route exposure — SettlementOperatorService + 4 FastAPI routes + server/main.py wiring (ST-39..ST-47)
- **Not in Scope:** Live DB, batch persistence, Telegram wiring, full SENTINEL pre-public sweep
- **Suggested Next Step:** WARP🔹CMD review; Gate 1c after merge
