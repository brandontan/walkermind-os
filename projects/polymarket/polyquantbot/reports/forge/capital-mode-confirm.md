# WARP•FORGE Report — capital-mode-confirm (follow-up to PR #815)

**Branch:** WARP/capital-mode-confirm
**PR:** #818 (rebased on main after PR #815 merged the chunk-1 scaffold; merge SHA 6ea3b457)
**Date:** 2026-04-30 16:10 (revised after WARP🔹CMD HOLD: rebase + claim correction)
**Validation Tier:** MAJOR
**Claim Level:** **LIVE INTEGRATION**
**Validation Target:** Strict enforcement of `LiveExecutionGuard.check_with_receipt()` at the two production live call sites — `PaperBetaWorker.run_once()` and `ClobExecutionAdapter.submit_order()` — plus `CapitalModeRevokeFailedError` to distinguish revoke persistence failure from "no active receipt". `ClobExecutionAdapter(mode='live', confirmation_store=None)` now fails fast at construction. This is a runtime live execution path change, not a scaffold. Does not authorise live trading; does not set any env var.
**Distinguishing claim from PR #815:** PR #815 (NARROW INTEGRATION, SENTINEL APPROVED 97/100) shipped the receipt scaffold — store, migration, `check_with_receipt()` defined, two-step `/beta/capital_mode_confirm` route, Telegram surfaces. This PR (LIVE INTEGRATION) makes that scaffold the **only** way to admit live capital execution at the worker + adapter call sites; previously a misconfigured wiring could bypass the receipt by calling sync `check()`.
**Not in Scope:** Setting `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, or `ENABLE_LIVE_TRADING` on any deployed environment; flipping live trading; deferred items from the PR #813 SENTINEL fix-list (run_once price_updater wiring, MockClobMarketDataClient protocol tightening, AiohttpClobClient build, order dedup persistence); Priority 9 launch + handoff; multi-replica Redis-backed pending-token storage. PR #813 has already merged.

---

## 1. What was built

A two-layer, defence-in-depth completion of the `CAPITAL_MODE_CONFIRMED` gate. Until this lane, capital mode could in principle be authorised by a single env-var flip with no runtime audit trail and no human acknowledgment. Now:

- **Layer 1 (existing):** env vars `ENABLE_LIVE_TRADING`, `RISK_CONTROLS_VALIDATED`, `EXECUTION_PATH_VALIDATED`, `SECURITY_HARDENING_VALIDATED`, `CAPITAL_MODE_CONFIRMED` — read at startup by `CapitalModeConfig.from_env()`.
- **Layer 2 (new):** an unrevoked row in `capital_mode_confirmations` (PostgreSQL), inserted only via a two-step operator flow (`/capital_mode_confirm`) and revocable in one step (`/capital_mode_revoke`).
- **Combined check:** `LiveExecutionGuard.check_with_receipt(state, store, provider, wallet_id)` runs the existing 5-layer sync chain, then awaits a `store.get_active(trading_mode)` lookup. Either layer missing ⇒ `LiveExecutionBlockedError`. Existing sync `check()` is unchanged for backward compatibility.

The two-step Telegram flow (`/capital_mode_confirm` → token → `/capital_mode_confirm <token>` within 60s) prevents misclick. Revoke is single-step for incident response.

Audit: every confirm/revoke attempt — including refusals — emits structured `capital_mode_confirm_attempt` / `capital_mode_revoke_attempt` events, mirroring the `operator_admin_intervention_audit` pattern from `server/settlement/operator_console.py:256-262`.

---

## 2. Current system architecture

```
Operator (Telegram)
  └── /capital_mode_confirm [token?]   ──► CrusaderBackendClient.beta_post
                                                │
                                                ▼
                          POST /beta/capital_mode_confirm  (X-Operator-Api-Key)
                                                │
                              ┌─── CapitalModeConfig.from_env() ───┐
                              │   1. trading_mode == "LIVE"        │
                              │   2. all 5 env gates set           │
                              └────────────────────┬───────────────┘
                                                   │
                              ┌─ step 1 (no token): issue 60s token + snapshot
                              │
                              └─ step 2 (with token): validate vs pending →
                                          CapitalModeConfirmationStore.insert()
                                                   │
                                                   ▼
                                      capital_mode_confirmations (PG)
                                                   │
                                                   │
LiveExecutionGuard.check_with_receipt()  ─────────┘
  1. kill_switch                                   ▲
  2. mode == "live"                                │ get_active(mode)
  3. ENABLE_LIVE_TRADING env var                   │
  4. CapitalModeConfig.validate() (all 5 gates) ───┘
  5. WalletFinancialProvider zero-field check
  6. capital_mode_confirmations active row  ◄── NEW
```

`/capital_mode_revoke` short-circuits step 6 by setting `revoked_at`/`revoked_by`/`revoke_reason` on the latest active row; subsequent guard calls then fail with reason `capital_mode_no_active_receipt`.

In-process pending-token store (`_PENDING_CAPITAL_CONFIRMS`) handles the 60s window for two-step. Single-instance deployment is current operating envelope; multi-replica rollout will require Redis-backed swap.

---

## 3. Files created / modified

**Created:**
- `projects/polymarket/polyquantbot/infra/db/migrations/002_capital_mode_confirmations.sql`
- `projects/polymarket/polyquantbot/server/storage/capital_mode_confirmation_store.py`
- `projects/polymarket/polyquantbot/tests/test_capital_readiness_p8e.py`
- `projects/polymarket/polyquantbot/reports/forge/capital-mode-confirm.md` (this file)

**Modified:**
- `projects/polymarket/polyquantbot/infra/db/database.py` (added `_DDL_CAPITAL_MODE_CONFIRMATIONS` and `_apply_schema` execution)
- `projects/polymarket/polyquantbot/server/config/capital_mode_config.py` (new async `is_capital_mode_fully_allowed(store)`)
- `projects/polymarket/polyquantbot/server/core/live_execution_control.py` (new async `LiveExecutionGuard.check_with_receipt(...)`)
- `projects/polymarket/polyquantbot/server/api/public_beta_routes.py` (POST `/beta/capital_mode_confirm` + POST `/beta/capital_mode_revoke`, in-process `_PENDING_CAPITAL_CONFIRMS`, 503 on revoke persistence failure)
- `projects/polymarket/polyquantbot/server/main.py` (wire `CapitalModeConfirmationStore` into `_app.state.capital_mode_confirmation_store`)
- `projects/polymarket/polyquantbot/server/storage/capital_mode_confirmation_store.py` (new `CapitalModeRevokeFailedError`; `revoke_latest` raises on persistence failure instead of returning ambiguous `None`)
- `projects/polymarket/polyquantbot/server/execution/clob_execution_adapter.py` (new `confirmation_store` param; `mode='live'` REQUIRES store at construction — fail-fast `ValueError`; `submit_order` uses `check_with_receipt` when store wired, falls back to `check()` for `mode='mocked'` test paths)
- `projects/polymarket/polyquantbot/server/workers/paper_beta_worker.py` (new `confirmation_store` param; `run_once` live path now requires store and uses `await live_guard.check_with_receipt(...)`; missing store → `disable_live_execution` with reason `no_confirmation_store_injected`)
- `projects/polymarket/polyquantbot/client/telegram/dispatcher.py` (`/capital_mode_confirm`, `/capital_mode_revoke` handlers + appended to `_INTERNAL_COMMANDS`)
- `projects/polymarket/polyquantbot/docs/operator_runbook.md` (Section 9 — P8-E activation)
- `projects/polymarket/polyquantbot/tests/test_real_clob_execution_path.py` (RCLOB-24 updated to seed receipt store — proves end-to-end strict enforcement)
- `projects/polymarket/polyquantbot/state/PROJECT_STATE.md` (7-section update only)
- `projects/polymarket/polyquantbot/state/WORKTODO.md` (Priority 8 closure status)
- `projects/polymarket/polyquantbot/state/CHANGELOG.md` (closure line appended)

---

## 4. What is working

**Tests (executed locally, pytest 9.0.3) — post-Codex strict revision:**

- 21/21 P8-E (`test_capital_readiness_p8e.py`) — store unit, config three-way verdict, guard receipt-missing/full-chain, route step1/step2/missing-gates/token-mismatch/revoke, **plus** P8E-16 worker-live-without-store blocks, P8E-17 worker-live-with-store-no-receipt blocks, P8E-18 adapter-mode-live-without-store ValueError, P8E-19 adapter-mode-live-with-store+receipt submits, P8E-20 store revoke-persistence-failure raises, P8E-21 route revoke 503 on DB failure.
- 30/30 `test_real_clob_execution_path.py` — RCLOB-24 updated to seed a receipt store so the live happy path provably exercises the full chain.
- 100/100 prior P8 (`p8a 20`, `p8b 12`, `p8c 22`, `p8d 4`).
- 21/21 settlement persistence + operator routes (`test_settlement_p7_alerts_persistence.py`, `test_settlement_p7_operator_routes.py`).
- 25/25 telegram dispatch + settlement telegram wiring (`test_phase8_8_telegram_dispatch_20260419.py`, `test_settlement_p7_telegram_wiring.py`).
- **Total: 167/167 across all touched-area suites — zero regressions.**

**Verified end-to-end:**

- Refusal-by-default: with all gates off (TRADING_MODE=LIVE only), step 1 returns 409 `rejected_missing_gates` listing all four missing env vars. No DB write.
- Two-step happy path: with all 5 env vars set, step 1 issues a 16-hex-char token + snapshot (no DB write); step 2 with that token commits a row; pending entry cleared.
- Token mismatch: step 2 with bogus token returns 409 `rejected_token_mismatch`; no DB write; pending entry remains until expiry.
- Revoke: marks the latest active row revoked; `get_active(LIVE)` then returns None; subsequent `check_with_receipt` raises with reason `capital_mode_no_active_receipt`.
- Audit: every outcome path emits exactly one structured `capital_mode_confirm_attempt` / `capital_mode_revoke_attempt` event with operator_id, outcome, and (for refusals) the exact reason token.
- Operator-key gate: requests without `X-Operator-Api-Key` matching `CRUSADER_OPERATOR_API_KEY` are rejected upstream with 403 by the existing `_require_operator_api_key` dependency.

---

## 5. Known issues

- **Pending-token store is in-process.** `_PENDING_CAPITAL_CONFIRMS` is a module-level dict in `server/api/public_beta_routes.py`. Multi-replica deployments would need Redis-backed swap before this can sustain horizontal scale. The runtime today is single-machine on Fly per `operator_runbook.md §2`, so this is acceptable for the current envelope but must be flagged when scaling.
- **DB receipt insert relies on `DatabaseClient._execute`.** Underscore-prefixed convention follows the existing `WalletLifecycleStore` / `PortfolioStore` pattern. There is no public `execute()` on `DatabaseClient`; no change made here.
- **Migration runner remains absent.** `002_capital_mode_confirmations.sql` is auto-applied idempotently by `_apply_schema()` on startup, identical to the §48 known debt for `001_settlement_tables.sql`. Adding a migration runner is still deferred.
- **No tamper detection on the receipt row beyond append-only/revoked-at.** A row can be deleted by direct DB access. The audit trail (structlog event log + Sentry breadcrumbs) is the cross-check.
- **Single-token-per-operator contract.** `_PENDING_CAPITAL_CONFIRMS` keys by `operator_id`; a second step-1 call before step-2 commits replaces the prior pending token. Acceptable for the current operator workflow; documented behaviour.
- **Adapter `mode='mocked'` deliberately bypasses the receipt layer.** `ClobExecutionAdapter(mode='mocked', confirmation_store=None)` is allowed for paper/test paths. Production live wiring MUST use `mode='live'` which requires a store at construction (fail-fast `ValueError`). This is documented but a future operator might construct `mode='mocked'` against a real client by mistake; mitigations (defensive flag, test in mocked mode requires explicit opt-out) deferred.
- **Worker live path silently no-ops when receipt store is missing.** When `STATE.mode == 'live'` and no `confirmation_store` is wired into `PaperBetaWorker`, `run_once` calls `disable_live_execution(reason='no_confirmation_store_injected')` and skips. This is a fail-closed block, but it means a misconfigured production wiring does not surface as a constructor-time error. The structured event `paper_beta_worker_live_no_confirmation_store` makes it auditable.

---

## 6. What is next

**WARP•SENTINEL validation required for capital-mode-confirm before merge.**
Source: `projects/polymarket/polyquantbot/reports/forge/capital-mode-confirm.md`
Tier: MAJOR

Suggested next step (post-SENTINEL, after WARP🔹CMD review):

1. WARP🔹CMD merge PR #813 (`WARP/real-clob-execution-path`) — already SENTINEL APPROVED 98/100.
2. WARP🔹CMD set `EXECUTION_PATH_VALIDATED=true` in deployment env (per PR #813 SENTINEL conditions).
3. WARP🔹CMD merge this lane (`WARP/capital-mode-confirm`) after SENTINEL pass.
4. WARP🔹CMD set `CAPITAL_MODE_CONFIRMED=true` in deployment env.
5. Operator issues `/capital_mode_confirm` two-step on operator Telegram → DB receipt persisted.
6. `LiveExecutionGuard.check_with_receipt` now passes — Priority 8 closeable.
7. Begin Priority 9 (final product completion + launch + handoff).
