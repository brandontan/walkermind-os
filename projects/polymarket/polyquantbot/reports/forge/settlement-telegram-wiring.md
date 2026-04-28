# WARP•FORGE REPORT: settlement-telegram-wiring
Branch: WARP/settlement-telegram-wiring
Date: 2026-04-28 17:00 Asia/Jakarta

---

## Validation Metadata

- Branch: WARP/settlement-telegram-wiring
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target: `client/telegram/backend_client.py`, `client/telegram/dispatcher.py` — Telegram command wiring for 4 settlement operator commands (§48 Gate 1c)
- Not in Scope: Live DB integration, batch result persistence, full SENTINEL pre-public sweep, live Fly.io deploy test
- Suggested Next Step: WARP🔹CMD review before merge; Priority 8 capital readiness after Gate 1c merged

---

## 1. What Was Built

Gate 1c wires the OperatorConsole HTTP routes (Gate 1b, PR #787) to Telegram operator commands. Operators can now manage settlement/retry/reconciliation directly from Telegram without raw HTTP calls.

**`CrusaderBackendClient`** (`client/telegram/backend_client.py`) — 2 new helpers:
- `_settlement_headers()` — reads `SETTLEMENT_ADMIN_TOKEN` env var; returns `X-Settlement-Admin-Token` header dict
- `settlement_get(path)` — GET with settlement headers; mirrors `orchestration_get()` pattern
- `settlement_post(path, payload)` — POST with settlement headers; mirrors `orchestration_post()` pattern

**`TelegramDispatcher`** (`client/telegram/dispatcher.py`) — 4 new operator commands:

| Command | Backend endpoint | Notes |
|---|---|---|
| `/settlement_status <workflow_id>` | GET /admin/settlement/status/{id} | Returns status, retry count, amount, mode, blocked reason, wallet |
| `/retry_status <workflow_id>` | GET /admin/settlement/retry/{id} | Returns total attempts, exhausted flag, last error, next retry at |
| `/failed_batches` | GET /admin/settlement/failed-batches | Acknowledges empty list + batch persistence limitation clearly |
| `/settlement_intervene <workflow_id> <action> [reason]` | POST /admin/settlement/intervene | Applies admin intervention; surfaces 404 (workflow not found) cleanly |

All 4 commands added to `_INTERNAL_COMMANDS` set — guarded by existing `_is_internal_command_allowed()` (operator chat_id match required). Non-operator chats receive `unknown_command` outcome.

---

## 2. Current System Architecture

```
[Telegram Operator]
        │
        ▼
TelegramDispatcher.dispatch()
  /settlement_status <wf_id>  ──→ settlement_get(/admin/settlement/status/{wf_id})
  /retry_status <wf_id>       ──→ settlement_get(/admin/settlement/retry/{wf_id})
  /failed_batches             ──→ settlement_get(/admin/settlement/failed-batches)
  /settlement_intervene       ──→ settlement_post(/admin/settlement/intervene, {...})
        │ (all guarded by operator chat_id)
        ▼
CrusaderBackendClient
  settlement_get(path)   → X-Settlement-Admin-Token header → SETTLEMENT_ADMIN_TOKEN env
  settlement_post(path)  → X-Settlement-Admin-Token header → SETTLEMENT_ADMIN_TOKEN env
        │
        ▼
FastAPI /admin/settlement/* (Gate 1b — PR #787 merged)
        │
        ▼
SettlementOperatorService → OperatorConsole → SettlementPersistence
        │
        ▼
[PostgreSQL: settlement_events, settlement_retry_history]
```

---

## 3. Files Created / Modified (full repo-root paths)

**Created:**
```
projects/polymarket/polyquantbot/tests/test_settlement_p7_telegram_wiring.py
projects/polymarket/polyquantbot/reports/forge/settlement-telegram-wiring.md
```

**Modified:**
```
projects/polymarket/polyquantbot/client/telegram/backend_client.py
projects/polymarket/polyquantbot/client/telegram/dispatcher.py
projects/polymarket/polyquantbot/state/PROJECT_STATE.md
projects/polymarket/polyquantbot/state/WORKTODO.md
projects/polymarket/polyquantbot/state/CHANGELOG.md
```

---

## 4. What Is Working

- All 8 Gate 1c tests pass: ST-48..ST-55 (8/8)
- `/settlement_status <workflow_id>` — guarded, calls correct backend path, formats reply with status/retry/amount/mode/blocked_reason/wallet
- `/retry_status <workflow_id>` — guarded, calls correct backend path, formats reply with attempts/exhausted/last_error/next_retry_at
- `/failed_batches` — guarded, calls correct backend path, returns empty-list acknowledgement with batch persistence limitation note
- `/settlement_intervene <workflow_id> <action> [reason]` — guarded, parses args, calls backend, formats result, surfaces 404 as clean "not found" message
- Backend errors (any non-ok response) surfaced cleanly — no exception propagation to Telegram user
- Missing-arg usage hints returned for commands requiring arguments
- `SETTLEMENT_ADMIN_TOKEN` env var read by `_settlement_headers()` — same pattern as orchestration token; never hardcoded

---

## 5. Known Issues

- `get_failed_batches()` (service layer) always returns `[]` — this is a carry-over from Gate 1b; batch result persistence is not in the current lane. The `/failed_batches` Telegram command acknowledges this limitation explicitly in its reply.
- `apply_admin_intervention()` does not persist the intervention record — existing known issue from Gate 1b; the `/settlement_intervene` Telegram reply includes a note about this.
- `SETTLEMENT_ADMIN_TOKEN` env var must be set in the Fly.io deployment for settlement commands to authenticate against the backend; missing token will produce 403 from the backend, which is surfaced as `http_403` in the Telegram error reply.

---

## 6. What Is Next

- Priority 8: Production-capital readiness gating — 5 chunked FORGE tasks, each requiring SENTINEL MAJOR sweep before merge
  - P8-A: Capability boundary review + capital-mode config model (§49-50)
  - P8-B: Capital risk controls hardening (§51)
  - P8-C: Live execution readiness audit (§52)
  - P8-D: Security + observability hardening (§53)
  - P8-E: Capital validation + claim review (§54)
- After all P8 SENTINEL gates pass: Priority 9 final product completion, launch assets, and handoff

---

## Metadata

- **Validation Tier:** STANDARD
- **Claim Level:** NARROW INTEGRATION (Telegram command surface over existing Gate 1b HTTP routes; no new infra)
- **Validation Target:** §48 Gate 1c — 4 Telegram settlement operator commands + 2 backend client helpers (ST-48..ST-55)
- **Not in Scope:** Live DB, batch persistence, full SENTINEL pre-public sweep, Fly.io deploy test
- **Suggested Next Step:** WARP🔹CMD review; Priority 8 after merge
