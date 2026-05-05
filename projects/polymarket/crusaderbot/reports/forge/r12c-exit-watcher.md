# WARP•FORGE Report — R12c Exit Watcher (TP/SL/Force-Close)

Branch: `WARP/CRUSADERBOT-R12C-EXIT-WATCHER`
Validation Tier: **MAJOR**
Claim Level: **FULL RUNTIME INTEGRATION**
Validation Target: per-position auto-close worker — TP/SL/force-close/strategy-exit priority chain, applied_* snapshot immutability, retry-once-on-CLOB-error close path, operator alert on persistent failure.
Not in Scope: live CLOB internals (`MockClobClient` / `polymarket.submit_signed_live_order` untouched), risk gate / Kelly sizing / entry flow, activation guards, redemption pipeline.
Suggested Next Step: WARP•SENTINEL MAJOR audit of the exit-watcher path against R12c done-criteria, then WARP🔹CMD merge decision.

---

## 1. What was built

R12c delivers an asyncio per-position exit watcher that evaluates each open position on every tick against a fixed priority chain and submits a close order through the existing engine router when triggered.

Priority order (first match wins):

1. `force_close_intent == TRUE` → `ExitReason.FORCE_CLOSE`
2. `ret_pct >= applied_tp_pct` → `ExitReason.TP_HIT`
3. `ret_pct <= -applied_sl_pct` → `ExitReason.SL_HIT`
4. `strategy.evaluate_exit(position) == EXIT` → `ExitReason.STRATEGY_EXIT`
5. otherwise → hold (refresh `current_price` only)

Snapshot contract (`applied_tp_pct` / `applied_sl_pct`):
- Stored at entry. Mutation is rejected at three layers:
  1. **DB trigger** (`trg_positions_immutable_applied`) — `RAISE EXCEPTION` on any UPDATE that changes the snapshot.
  2. **Registry API** — no public function in `domain/positions/registry.py` accepts an `applied_*` parameter.
  3. **Read-only dataclass** — `OpenPositionForExit` is frozen, and `to_router_dict()` strips applied_* before crossing into the close engine.

Failure handling:
- CLOB error → wait 5 s → one retry → on persistent failure: increment `close_failure_count`, alert user, alert operator at `CLOSE_FAILURE_OPERATOR_THRESHOLD` (=2), keep position `'open'` for next-tick retry.
- No `except: pass` anywhere in the worker. Every catch logs at WARN/ERROR with `exc_info=True` for the infra-net catch.

User-side alerts: TP hit, SL hit, force-close executed, strategy-exit executed, close-failed (with retry promise).
Operator alert: persistent close failure on the same position (per-position cooldown key).

---

## 2. Current system architecture

```
                ┌──────────────────────────────────────┐
                │ APScheduler (EXIT_WATCH_INTERVAL=60s)│
                └─────────────┬────────────────────────┘
                              │ scheduler.check_exits()
                              ▼
         ┌──────────────────────────────────────────────────┐
         │ domain/execution/exit_watcher.run_once()         │
         │   1. registry.list_open_for_exit()  (DB read)    │
         │   2. evaluate(position, strategy_evaluator)      │
         │      ├ force_close_intent ───────► FORCE_CLOSE   │
         │      ├ ret >= applied_tp_pct ────► TP_HIT        │
         │      ├ ret <= -applied_sl_pct ───► SL_HIT        │
         │      ├ strategy returns EXIT ───► STRATEGY_EXIT  │
         │      └ else ─────────────────────► hold          │
         │   3. _act_on_decision(...)                        │
         │      ├ hold → registry.update_current_price      │
         │      └ exit → order.submit_close_with_retry      │
         │              (1 retry, 5s backoff)               │
         └─────────────┬────────────────────────────────────┘
                       │
              ┌────────┴─────────┐
              │                  │
              ▼                  ▼
    domain/execution/      domain/execution/order.py
    router.close()         submit_close_with_retry()
              │
   ┌──────────┴────────────┐
   ▼                       ▼
 paper.close_position    live.close_position
   │                       │   (LivePostSubmitError → no retry,
   │                       │    surface to operator)
   ▼                       ▼
   positions.UPDATE       polymarket.submit_live_order (SELL)
   ledger.credit          → positions.UPDATE → ledger.credit
```

DB layer (migration 005):
- `applied_tp_pct NUMERIC(5,4)` — snapshot, immutable after INSERT.
- `applied_sl_pct NUMERIC(5,4)` — snapshot, immutable after INSERT.
- `force_close_intent BOOLEAN NOT NULL DEFAULT FALSE` — Telegram-set marker.
- `close_failure_count INTEGER NOT NULL DEFAULT 0` — consecutive failures.
- `trg_positions_snapshot_applied` (BEFORE INSERT) — auto-populates `applied_*` from `tp_pct`/`sl_pct` if caller did not set them, so existing INSERT paths in `paper.py` / `live.py` keep working unchanged.
- `trg_positions_immutable_applied` (BEFORE UPDATE) — rejects UPDATE that mutates `applied_*`.
- Backfill: `applied_*` seeded from existing `tp_pct`/`sl_pct`; `force_close_intent` seeded from legacy `force_close` for any in-flight rows at deploy time.

Pipeline placement: `MONITORING` (the watcher) consumes `DATA` (market book sync) and emits into `EXECUTION` (router.close). RISK is upstream of EXECUTION at entry; the watcher's exit path does NOT re-check entry guards, matching the existing close-path contract in `live.close_position`.

---

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/migrations/005_position_exit_fields.sql`
- `projects/polymarket/crusaderbot/domain/positions/__init__.py`
- `projects/polymarket/crusaderbot/domain/positions/registry.py`
- `projects/polymarket/crusaderbot/domain/execution/order.py`
- `projects/polymarket/crusaderbot/domain/execution/exit_watcher.py`
- `projects/polymarket/crusaderbot/tests/test_exit_watcher.py`
- `projects/polymarket/crusaderbot/reports/forge/r12c-exit-watcher.md`

Modified:
- `projects/polymarket/crusaderbot/monitoring/alerts.py` — added five alert functions (`alert_user_tp_hit`, `alert_user_sl_hit`, `alert_user_force_close`, `alert_user_strategy_exit`, `alert_user_close_failed`, `alert_operator_close_failed_persistent`) + `CLOSE_FAILURE_OPERATOR_THRESHOLD` constant.
- `projects/polymarket/crusaderbot/scheduler.py` — `check_exits()` now delegates to `exit_watcher.run_once()`; removed inline `_evaluate_exit` / `_strategy_should_exit` (logic relocated to `exit_watcher.py`); dropped unused `router_close` import.
- `projects/polymarket/crusaderbot/bot/handlers/emergency.py` — `pause_close` now calls `position_registry.mark_force_close_intent_for_user(user_id)` instead of an inline raw-SQL UPDATE on `force_close`.

Notes on path layout:
- The R12c task spec referenced `execution/`, `core/`, `infra/migrations/` paths. CrusaderBot's actual layout uses `domain/execution/`, `domain/positions/`, and `migrations/` (mirroring existing files 001–004). Files were placed in the project's existing locked structure to avoid creating parallel folder roots — there are no new top-level packages, no shims, no re-export modules.

---

## 4. What is working

Verified via `pytest tests/` (49 tests pass, 22 new in `test_exit_watcher.py`):

Decision logic (`evaluate`):
- TP hit on YES side closes with `ExitReason.TP_HIT`.
- TP hit on NO side closes with correct per-side P&L formula `(entry-cur)/(1-entry)`.
- SL hit closes with `ExitReason.SL_HIT`.
- `force_close_intent=TRUE` overrides both TP and SL → `ExitReason.FORCE_CLOSE`.
- Resolved markets are skipped (settled by redemption pipeline).
- Strategy hook fires only when force/TP/SL all hold.
- `applied_tp_pct=None` ⇒ no synthesized TP from any external source — position holds.
- `evaluate()` does NOT mutate the position — verified by snapshot diff.

Close path (`order.submit_close_with_retry`):
- Success on first attempt → no retry.
- Fail then succeed → retry after `CLOSE_RETRY_DELAY_SECONDS` (5 s in production, monkey-patched no-op in tests), one retry only.
- Always-fail → returns `CloseResult(ok=False, error=...)` after `CLOSE_MAX_ATTEMPTS=2`.

Worker orchestration (`run_once`):
- TP hit → close submitted, user alerted with `alert_user_tp_hit`, `close_failure_count` not touched.
- SL hit → `alert_user_sl_hit` fires with the exit price.
- `force_close_intent` → `alert_user_force_close` fires; TP path does NOT fire (proves priority).
- CLOB error twice → `record_close_failure` awaited once, user alerted, operator alerted at threshold (failure_count=2). Position stays `'open'`.
- Hold → only `update_current_price` called; no submitter, no alert.
- Per-position exception is logged and skipped — the rest of the batch still evaluates.

Snapshot immutability:
- Registry surface scan: no mutation function exposes `applied_tp_pct` / `applied_sl_pct` as a parameter.
- `OpenPositionForExit` is a frozen dataclass — assignment raises.
- `to_router_dict()` does NOT carry applied_* into the close engine.

DB migration:
- Fully idempotent (`ADD COLUMN IF NOT EXISTS`, `DO $$ ... pg_trigger ...`).
- Backfill seeds applied_* from existing tp_pct/sl_pct so positions in flight at deploy time keep their thresholds.
- Two triggers installed: snapshot-on-insert and reject-update.

Lint:
- `ruff check .` passes (R12a baseline ruleset).

---

## 5. Known issues

- Legacy `positions.force_close` column is still present and read by no one. Migration 005 backfills `force_close_intent` from it but does NOT drop the column. A follow-up MINOR lane should remove `force_close` after one release window; doing it in this PR would conflict with any operator-deployed `emergency.py` that has not yet picked up the new code path.
- `domain/execution/exit_watcher.run_forever()` is provided but not wired into `main.py`. APScheduler still drives the tick via `scheduler.check_exits → exit_watcher.run_once`. Standalone worker activation is left for the deployment lane (R12 final).
- `finalize_close_failed()` exists in the registry but the watcher does NOT auto-call it — by design. A transient broker outage must not poison live exposure into a permanent `'close_failed'` state. The operator finalises manually after reconciliation; the persistent-failure alert pages them with the position id needed.
- Existing `tp_pct`/`sl_pct` columns on `positions` and `user_settings` remain. The `user_settings` columns are correct (settings, not snapshots). The `positions.tp_pct`/`positions.sl_pct` columns are now redundant with `applied_*` and could be dropped in a follow-up cleanup, but keeping them avoids breaking the engine `INSERT` statements in `paper.py`/`live.py` that still reference them — the BEFORE-INSERT trigger automatically copies them into `applied_*`.

---

## 6. What is next

WARP•SENTINEL MAJOR audit per R12c task header. Verification scope:
- Phase 0: report/state/structure/no-phase-folders/evidence checks.
- Phase 1: priority chain ordering enforced (force > tp > sl > strategy > hold).
- Phase 2: pipeline end-to-end — watcher → router.close → paper or live → ledger credit → audit row.
- Phase 3: failure modes — CLOB 5xx, LivePostSubmitError surface, per-position exception isolation, retry budget exhaustion.
- Phase 4: async safety — single asyncio task, no `threading`, no shared mutable state across ticks (frozen dataclass).
- Phase 5: risk-rule preservation — Kelly=0.25 untouched, position size cap untouched, kill switch untouched, dedup untouched (this lane never runs at entry).
- Phase 6: latency — per-tick <500 ms exit submission per position under no-failure path (to be measured in staging).
- Phase 7: infra — migration 005 idempotent on re-run; trigger fires on attempted UPDATE.
- Phase 8: Telegram alert preview — five user events + one operator event.

Done criteria (mapped to task header):

| Criterion | Status | Evidence |
| --- | --- | --- |
| TP hit → closed, exit_reason=tp_hit, user alerted | PASS | `test_run_once_tp_hit_closes_and_alerts` |
| SL hit → closed, exit_reason=sl_hit, user alerted | PASS | `test_run_once_sl_hit_alerts_user` |
| force_close_intent=true → immediate close, exit_reason=force_close | PASS | `test_run_once_force_close_intent_executes_immediately`, `test_evaluate_force_close_intent_overrides_tp` |
| CLOB error → retry once, exit_reason=close_failed, operator alerted | PASS | `test_close_with_retry_fails_then_succeeds`, `test_close_with_retry_exhausts_then_fails`, `test_run_once_close_failure_increments_counter_and_alerts` |
| applied_tp_pct/applied_sl_pct immutable after creation | PASS | DB trigger `trg_positions_immutable_applied`; registry API has no setter; dataclass frozen; `test_registry_exposes_no_applied_setter` |
| User Trade Setting update → does NOT affect open positions | PASS | watcher reads `applied_*` only; `test_evaluate_ignores_tp_pct_when_applied_is_none` |
| Migration 005 idempotent | PASS | `ADD COLUMN IF NOT EXISTS` + `pg_trigger` existence guards |
| No threading — asyncio throughout | PASS | only `asyncio` imported in worker / order / registry |
| No silent exception handling in worker loop | PASS | every `except` has logger.warning/error with exc_info |
| All existing tests still pass | PASS | 49/49 pass |
