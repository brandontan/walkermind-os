# multi-wallet-orchestration-phase-c — Priority 6 Phase C Forge Report

## Validation Metadata

- Branch: NWAP/multi-wallet-orchestration-phase-c
- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Validation Target: `server/orchestration/` — DB-backed WalletControlsStore, OrchestrationDecisionStore, OrchestratorService, orchestration admin API routes, Telegram admin commands, degraded-mode outcome, persistence failure surfacing (sections 41–42 of WORKTODO.md)
- Not in Scope: Live balance/risk data (market data integration deferred), full Telegram auth for admin commands (uses existing operator_chat_id guard), PostgreSQL end-to-end test against real DB
- Suggested Next Step: SENTINEL MAJOR validation for Priority 6 Phase C before merge

---

## 1. What Was Built

Priority 6 Phase C delivers the UX/API, recovery, and persistence layer for multi-wallet orchestration. A post-review fix pass addressed three findings from Gemini code review (atomic persist transaction, startup recovery wiring, dead code) and adds persistence failure surfacing to all admin mutation endpoints.

**Section 41 — UX/API and Recovery:**
- `server/api/orchestration_routes.py`: 7 FastAPI admin routes under `/admin/orchestration/` — wallet state, per-wallet health, enable/disable, global halt set/clear, decision log. All routes require `ORCHESTRATION_ADMIN_TOKEN` via `X-Orchestration-Admin-Token` header. Mutation routes (enable/disable/halt/clear) return 500 with `wallet_controls_persist_failed` reason when the DB persist call fails — in-memory state is still updated.
- `client/telegram/dispatcher.py`: 5 new admin commands — `/wallets`, `/wallet_enable`, `/wallet_disable`, `/halt`, `/resume`. All gated by existing `_is_internal_command_allowed()` (operator chat ID guard). Added to `_INTERNAL_COMMANDS` set.
- `client/telegram/backend_client.py`: 3 new HTTP helper methods — `orchestration_get`, `orchestration_post`, `orchestration_delete`. Each reads `ORCHESTRATION_ADMIN_TOKEN` from env and injects the `X-Orchestration-Admin-Token` header.
- `server/orchestration/wallet_orchestrator.py`: `degraded` outcome path — fires when all active candidates have `drawdown_pct > MAX_DRAWDOWN` (system-wide breach, distinct from per-wallet `risk_blocked`).

**Section 42 — Persistence and Validation:**
- `infra/db/database.py`: 2 new DDL blocks — `wallet_controls` table (per-wallet disable state + global halt, keyed by tenant_id/user_id/wallet_id; `__global__` magic key for halt) and `orchestration_decisions` table (routing decision log with index on user/decided_at).
- `server/orchestration/wallet_controls.py`: `load(db, tenant_id, user_id)` and `persist(db, tenant_id, user_id)` methods added. `persist()` acquires a single asyncpg connection and wraps DELETE + all INSERT statements in `async with conn.transaction()` — fully atomic. Returns False on exception; in-memory state is always authoritative during a session.
- `server/orchestration/schemas.py`: `OrchestrationDecision` frozen dataclass, `decision_from_result()` factory, `new_decision_id()` — decision log domain model.
- `server/orchestration/decision_store.py`: `OrchestrationDecisionStore` — async PostgreSQL persistence for routing decisions. `append()` is idempotent (ON CONFLICT DO NOTHING). `load_recent()` returns JSON-serializable dicts.
- `server/services/orchestration_service.py`: `OrchestratorService` — service layer that wires lifecycle store → controls store → aggregator → orchestrator → decision store. Mutation methods (`enable_wallet`, `disable_wallet`, `set_global_halt`, `clear_global_halt`) return persist status so callers can surface failures. `load_controls_from_db()` called at startup for recovery.
- `server/main.py`: `OrchestratorService` wired in lifespan after DB connects; `load_controls_from_db("system", "paper_user")` called immediately after wiring; `build_orchestration_router()` registered.
- `server/orchestration/__init__.py`: Phase C symbols exported.
- `tests/test_priority6_wallet_orchestration_phase_c.py`: 24 tests WO-28..WO-51 (all passing).

---

## 2. Current System Architecture

```
[Telegram admin commands]
/wallets /wallet_enable /wallet_disable /halt /resume
        │ (HTTP via CrusaderBackendClient.orchestration_*)
        ▼
[FastAPI] /admin/orchestration/* — orchestration_routes.py
        │ (requires ORCHESTRATION_ADMIN_TOKEN)
        │ (mutation routes surface 500 wallet_controls_persist_failed when DB write fails)
        ▼
OrchestratorService
        │
        ├── WalletLifecycleStore.list_wallets_for_user()
        │       → WalletCandidate[] (lifecycle status, zeroed financials)
        │
        ├── WalletControlsStore.build_overlay()
        │       → PortfolioControlOverlay (in-memory + DB-backed via load/persist)
        │       → persist() is atomic: single connection, conn.transaction()
        │
        ├── CrossWalletStateAggregator.aggregate()
        │       → CrossWalletState (health snapshot for admin visibility)
        │
        ├── WalletOrchestrator.route()
        │       │
        │       ├── Phase B pre-hook: global_halt → "halted"; filter disabled
        │       ├── Phase C: all active breached → "degraded"
        │       └── Phase A: WalletSelectionPolicy 6-filter chain
        │
        └── OrchestrationDecisionStore.append()
                → orchestration_decisions table (idempotent ON CONFLICT)

[PostgreSQL]
  wallet_controls        — per-wallet disable state + global halt
  orchestration_decisions — routing decision log
```

Risk constants remain locked from `server/schemas/portfolio.py`:
- MAX_DRAWDOWN = 0.08
- MAX_TOTAL_EXPOSURE_PCT = 0.10

---

## 3. Files Created / Modified (full repo-root paths)

**Created:**
```
projects/polymarket/polyquantbot/server/orchestration/decision_store.py
projects/polymarket/polyquantbot/server/api/orchestration_routes.py
projects/polymarket/polyquantbot/server/services/orchestration_service.py
projects/polymarket/polyquantbot/tests/test_priority6_wallet_orchestration_phase_c.py
projects/polymarket/polyquantbot/reports/forge/multi-wallet-orchestration-phase-c.md
```

**Modified:**
```
projects/polymarket/polyquantbot/infra/db/database.py
projects/polymarket/polyquantbot/server/orchestration/wallet_controls.py
projects/polymarket/polyquantbot/server/orchestration/schemas.py
projects/polymarket/polyquantbot/server/orchestration/wallet_orchestrator.py
projects/polymarket/polyquantbot/server/orchestration/__init__.py
projects/polymarket/polyquantbot/server/main.py
projects/polymarket/polyquantbot/client/telegram/backend_client.py
projects/polymarket/polyquantbot/client/telegram/dispatcher.py
projects/polymarket/polyquantbot/state/PROJECT_STATE.md
projects/polymarket/polyquantbot/state/WORKTODO.md
projects/polymarket/polyquantbot/state/CHANGELOG.md
```

---

## 4. What Is Working

- All 24 Phase C tests pass: WO-28..WO-51 (24/24).
- Phase A+B regression: 27/27 still passing (WO-01..WO-27).
- `WalletControlsStore.load()`: restores disabled set and global halt from DB rows; `__global__` key correctly identified; `is_disabled=False` rows are ignored.
- `WalletControlsStore.persist()`: atomic delete-then-insert inside a single asyncpg transaction (`async with conn.transaction()`); returns False on exception; in-memory state always authoritative during a session.
- `OrchestrationDecisionStore.append()`: idempotent ON CONFLICT DO NOTHING; `load_recent()` returns JSON-serializable dicts with ISO timestamps.
- `OrchestratorService.route()`: full pipeline from lifecycle fetch → overlay build → route → decision persist; `RouteResult` carries both result and persist status.
- `OrchestratorService` enable/disable/halt/clear: in-memory update + immediate atomic DB persist on every mutation; returns `(WalletControlResult, persist_ok)` for wallet toggles and `bool` for halt operations.
- `load_controls_from_db()` called at startup: control state is recovered from DB before the service becomes available to routes.
- Admin API mutation routes: return 500 `wallet_controls_persist_failed` when persist returns False — no silent ok on DB failure (WO-50, WO-51 confirmed).
- Admin API routes: 403 on missing/wrong token; 503 when service not wired; all 7 routes registered under `/admin/orchestration/`.
- `degraded` outcome: fires only when all active candidates breach drawdown ceiling; empty list and inactive-only lists correctly return `no_candidate` / `no_active_wallet` (WO-45 confirmed).
- Telegram commands: 5 new commands in `_INTERNAL_COMMANDS`, guarded by operator chat ID.
- DDL: `wallet_controls` and `orchestration_decisions` tables added to `_apply_schema()` — created idempotently on every `DatabaseClient.connect()`.

---

## 5. Known Issues

- Financial fields (`balance_usd`, `exposure_pct`, `drawdown_pct`) on `WalletCandidate` default to 0.0 — live mark-to-market data is deferred to the market data integration lane. The risk gate threshold checks (which use these values) will not trigger for zero-valued candidates.
- `OrchestratorService` uses hardcoded `tenant_id="system"` / `user_id="paper_user"` in the API routes (`_DEFAULT_SCOPE_*` constants) — per-user route binding deferred to full multi-user rollout.
- Telegram `/wallets` command does not display halt state from the overlay — it reads from the aggregate API which does not expose the global halt flag directly. Operators should use `/halt` and `/resume` commands to check state implicitly.
- When persist() returns False on a mutation, in-memory state is already updated — the control change is live for the session but will not survive a restart. This is expected behavior and logged at WARNING level.

---

## 6. What Is Next

- SENTINEL MAJOR validation required before merge.
- Priority 7 remaining: FastAPI routes for OperatorConsole (§47) and Telegram wiring for settlement status.
- Priority 7 PostgreSQL DDL migration confirmation (DDL already added to `infra/db/database.py` in PR #777 fix).
- Priority 8: Production-capital readiness gating.
- Pre-public SENTINEL/check-all sweep covering P4, P5, P6 full, P7 full.

---

## Metadata

- **Validation Tier:** MAJOR
- **Claim Level:** NARROW INTEGRATION (extends Phase A+B; no new external infra; DB writes via existing DatabaseClient pool)
- **Validation Target:** Sections 41–42 — UX/API, recovery, persistence, service wiring, persistence failure surfacing, integration tests (WO-28..WO-51)
- **Not in Scope:** Live financial data, per-user route binding, full SENTINEL pre-public sweep
- **Suggested Next Step:** SENTINEL validation of `NWAP/multi-wallet-orchestration-phase-c` before merge
