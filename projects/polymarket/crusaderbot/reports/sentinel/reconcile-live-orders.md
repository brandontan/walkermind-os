# WARP•SENTINEL — WARP-74 Chunk A (reconcile-live-orders, PR #1612)

Validator: WARP•SENTINEL (WARP🔹CMD-directed, WARP-74 dual-validation)
Branch: WARP/ROOT/reconcile-live-orders
PR: #1612 — Chunk A, detection-only
Environment: dev / pre-merge code-truth audit (live infra + Telegram not reachable from container → warn-only; risk-rule preservation ENFORCED)
Tier: MAJOR (live order surface; detection/telemetry-only)

## TEST PLAN

Phases run against code truth (not the PR narrative): Phase 0 pre-test, then
functional (the broker↔DB diff), failure modes, async safety, risk-rule
preservation (the crux — must prove zero capital-path effect), infra fail-soft,
and operator-page behaviour. Latency N/A (background 120s sweep).

## FINDINGS

Phase 0 — Pre-test: PASS.
- Forge report present, correct path + naming, all 6 sections + metadata: `projects/polymarket/crusaderbot/reports/forge/reconcile-live-orders.md`.
- `state/PROJECT_STATE.md` updated (7-section surgical). No `phase*/` folders. No file deletions (no hard-delete policy to honour). Implementation evidence present.

Phase 1 — Functional (the diff): PASS.
- `reconcile.py:110 reconcile_once` pulls `client.get_open_orders()` and diffs vs DB. ORPHAN = broker-open whose DB row is non-open or absent; in_sync = DB row in `STATUS_OPEN`; DB_ONLY = DB-open broker id absent from broker set (`reconcile.py:166-184`).
- `STATUS_OPEN` imported from `lifecycle.py:49` — "what counts as open" single-sourced with the poll loop (no drift between the two reconcilers).
- 10/10 hermetic tests pass (`tests/test_warp74_reconcile.py`): in-sync, orphan-untracked, orphan terminal-drift, db-only, malformed-payload, throttle, two fail-soft paths, config error, paper-skip.

Phase 3 — Failure modes: PASS.
- CLOB config/auth error → `errors=1`, no raise (`reconcile.py:132-135`).
- `get_open_orders` failure → `errors=1`, returns, `aclose` still runs in `finally` (`reconcile.py:140-143, 189-192`).
- DB load failure → `errors=1` (`reconcile.py:150-153`).
- Malformed broker row (non-dict / None) → `_broker_id` returns "" and is filtered (`reconcile.py:75`), never `AttributeError` — regression-pinned.
- Operator page wrapped in try/except (`reconcile.py:269-273`); `aclose` failure logged not raised (`reconcile.py:191-192`).

Phase 4 — Async safety: PASS.
- Scheduler job `live_order_reconcile` registered `max_instances=1, coalesce=True` (`scheduler.py`) → no concurrent `reconcile_once`, so the module-level `_last_orphan_alert` throttle dict has a single writer. Prune bound `_MAX_ALERT_KEYS=4096`. No threading; asyncio-only.

Phase 5 — Risk-rule preservation (CRUX): PASS — zero capital-path effect PROVEN.
- `reconcile.py` contains ZERO `INSERT`/`UPDATE` (grep): the only writes are `audit.write` + `notify_operator`. It never submits, cancels, sizes, gates, or mutates an `orders`/`positions` row. Orphan remediation is explicitly deferred to the operator / Chunk B (`reconcile.py` module docstring).
- Risk gate, execution, sizing, Kelly, `ENABLE_LIVE_TRADING`, and `OrderLifecycleManager.poll_once` are untouched by this diff (no edits outside the new module + scheduler/config wiring).
- Paper / non-live short-circuit before any client is built: `if not s.USE_REAL_CLOB: skipped=True` (`reconcile.py:126`).

Phase 7 — Infra: PASS (fail-soft). Uses the existing asyncpg pool with short-lived `acquire()`; every DB path is fail-soft. No new infra dependency. Config validator rejects `RECONCILE_INTERVAL_SEC<=0` at load (APScheduler-safe).

Phase 8 — Telegram: PASS. Operator page via the existing `notify_operator`, throttled per-orphan (`ORPHAN_ALERT_COOLDOWN_SEC=600`), capped at `_MAX_PAGED_ORPHANS=20` per message. Non-blocking.

## CRITICAL ISSUES

None found.

## STABILITY SCORE

- Architecture 20/20 — clean reverse-direction reconciler, single-sourced STATUS_OPEN, mirrors lifecycle/complete-set precedent.
- Functional 20/20 — diff logic correct, 10 tests green.
- Failure modes 20/20 — every external path fail-soft + regression-pinned.
- Risk 20/20 — detection-only proven (zero INSERT/UPDATE; capital path untouched).
- Infra + Telegram 10/10 — fail-soft pool, throttled page, load-time validator.
- Latency 10/10 — N/A background sweep (120s), well clear of timeout budget.
- TOTAL: 95/100.

Observational (non-blocking, no score deduction):
- `_clob_factory` only catches `(ClobConfigError, ClobAuthError)` (`reconcile.py:132`); a generic factory error would escape. Identical to `lifecycle.poll_once`'s contract — consistent, low risk. Optional hardening: broaden to a catch-all `errors=1`.
- `known` map takes an arbitrary status if two order rows somehow share one `polymarket_order_id` (`reconcile.py:_load_db_state`). Slippage-retry reuses the row (one row per id), so this is effectively unreachable; cosmetic.

## GO-LIVE STATUS

VERDICT: APPROVED — 95/100, 0 critical.
Detection/telemetry-only with a proven-zero capital-path footprint, fully fail-soft, single-instance async-safe, and no-op in paper/non-live. Safe to merge independently of the path decision. (Per WARP🔹CMD: HELD pending the #1611 verdict + path decision — this is a validation verdict, not a merge.)

## FIX RECOMMENDATIONS

None required. Optional (P3, post-merge): broaden the `_clob_factory` except to a
catch-all for total never-raise symmetry with the broker/DB branches.

## TELEGRAM PREVIEW

Operator orphan page (throttled, on a real broker session only):
```
⚠️ LIVE ORDER ORPHANS
2 order(s) resting at the broker not tracked as open:
• 0xZ9… (db: untracked)
• 0xC3… (db: filled)
Reconcile via Polymarket dashboard or kill-switch cancel-all.
```
Counters land in `job_runs.metadata` per sweep: `{broker_open, db_open, in_sync, orphans, db_only, errors}`.
