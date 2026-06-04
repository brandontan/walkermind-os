# WARP-74 Chunk A — Live Order Reconciliation (broker-truth sweep)

Role: WARP•R00T
Branch: WARP/ROOT/reconcile-live-orders
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: the new broker-truth reconcile sweep (`domain/execution/reconcile.py`), its scheduler registration, the config knobs + validator, and the hermetic test suite — that it correctly diffs broker open orders against the DB, surfaces orphan/drift via audit + throttled operator page, and is provably detection-only (no cancel/size/gate/mutate) and no-op in paper/non-live.
Not in Scope: cancelling/auto-resolving orphans (a deliberate capital action — Chunk B kill-switch cancel-all and operator action own that); any change to the OrderLifecycleManager poll loop, the risk gate, execution, sizing, Kelly, or the `ENABLE_LIVE_TRADING` guard; a DB schema/migration (none added — reconcile writes only audit + logs).
Suggested Next Step: WARP•SENTINEL MAJOR validation of this lane, then merge, then Chunk B (kill-switch broker cancel-all) as a separate sequential PR.

---

## 1. What was built

A periodic **broker-truth reconciliation sweep** that closes a structural blind
spot in live-order tracking.

The existing `OrderLifecycleManager.poll_once()` reconciles the **DB → broker**
direction: it selects in-flight `mode='live'` DB orders (`status IN
(submitted, pending, partial_filled)`) and checks each against the broker via
`get_order(broker_id)`. It cannot see orders the broker has open that the DB does
**not** track as open — there is no enumeration of the broker's open-order set.

This lane adds the **reverse (broker → DB) direction**. `LiveOrderReconciler`
pulls `ClobAdapter.get_open_orders()` and diffs it against the `orders` table:

* **ORPHAN** — a broker-open order whose DB row is terminal (filled / cancelled /
  expired / stale) or absent entirely. This is uncontrolled live exposure: an
  ambiguous submit (`orders.status='unknown'` from `live.execute`'s post-submit
  path) that actually reached the book, a crash between submit and persist, or an
  order placed manually outside the bot. Each orphan is audited
  (`live_order_orphan_detected`, with `db_status` = the terminal status or
  `untracked`) and a throttled operator page is sent.
* **DB_ONLY** — a DB-open order the broker no longer lists as open (it filled /
  cancelled / expired). The poll loop owns resolving these (it polls each by id);
  reconcile only **counts** them so the drift is visible in `job_runs.metadata`.

It is **detection / telemetry only** — it never cancels, sizes, gates, or mutates
an `orders` / `positions` row.

## 2. Current system architecture

```
                 ClobAdapter.get_open_orders()  ── broker-open set ─┐
                                                                    ▼
  scheduler (interval=RECONCILE_INTERVAL_SEC, gated by    LiveOrderReconciler
  RECONCILE_LIVE_ORDERS_ENABLED)  ──▶  reconcile_once()        .reconcile_once()
                                                                    │ diff
   orders table (mode='live')  ── db-open set + known-status map ───┤
                                                                    ▼
                          ┌─────────────┬──────────────┬────────────────┐
                       in_sync        ORPHAN          DB_ONLY        (counts)
                      (no action)   audit + throttled  count only
                                    operator page      (poll resolves)
```

* **Paper / non-live short-circuit**: `USE_REAL_CLOB=False` returns
  `{skipped: True, …}` before any client is built — nothing rests at a broker.
* **Fail-soft**: a CLOB config/auth error, a `get_open_orders` failure, or a DB
  load failure each logs and returns with `errors=1`; the sweep never raises, so
  a single bad pass can't stop the scheduler job. The CLOB client is always
  `aclose()`d in a `finally`.
* **Orphan page throttle**: a module-level `_last_orphan_alert` map suppresses
  re-paging the same orphan within `ORPHAN_ALERT_COOLDOWN_SEC` (600s), bounded by
  a prune at `_MAX_ALERT_KEYS`. A persistent orphan stays on the operator's radar
  without spamming every 120s tick.
* **Status source of truth**: `STATUS_OPEN` is imported from
  `domain/execution/lifecycle.py` so "what counts as open" stays single-sourced
  with the poll loop.

## 3. Files created / modified (full repo-root paths)

Created:
* `projects/polymarket/crusaderbot/domain/execution/reconcile.py` — `LiveOrderReconciler` + `_broker_id` helper + module-level `reconcile_once()` shim / `get_default_reconciler()`.
* `projects/polymarket/crusaderbot/tests/test_warp74_reconcile.py` — 9 hermetic tests (fake asyncpg pool/conn + fake CLOB client; no DB/network/Telegram).
* `projects/polymarket/crusaderbot/reports/forge/reconcile-live-orders.md` — this report.

Modified:
* `projects/polymarket/crusaderbot/scheduler.py` — new `reconcile_live_orders()` wrapper (mirrors `reconcile_complete_set`) + `live_order_reconcile` interval job registration gated by `RECONCILE_LIVE_ORDERS_ENABLED`.
* `projects/polymarket/crusaderbot/config.py` — `RECONCILE_LIVE_ORDERS_ENABLED: bool = True`, `RECONCILE_INTERVAL_SEC: int = 120`, and a `validate_reconcile_interval` `@field_validator` rejecting `<= 0`.
* `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — Last Updated + Status + IN PROGRESS + NEXT PRIORITY (7-section surgical update).
* `projects/polymarket/crusaderbot/state/CHANGELOG.md` — one appended lane entry.

## 4. What is working

* 9/9 hermetic tests pass (`pytest test_warp74_reconcile.py`): paper-mode skip (no broker call), in-sync (no orphan/page), orphan-untracked (audit + page + `db_status='untracked'`), orphan terminal-drift (`db_status='filled'`), db-only drift (counted, no page), orphan page throttle (suppressed within cooldown, re-pages after), fail-soft on broker error (`errors=1`, `aclose` still runs), fail-soft on DB error, CLOB config error (`errors=1`).
* `ruff check` clean on all touched/new files.
* `RECONCILE_INTERVAL_SEC` validator confirmed: accepts 120, rejects 0 and -5 (direct classmethod exercise — APScheduler requires strictly-positive seconds).
* Scheduler registration mirrors the proven `complete_set_reconcile` precedent (gated, `max_instances=1`, `coalesce=True`); returns the counters dict so the existing `_job_tracker_listener` captures it into `job_runs.metadata`.

## 5. Known issues

* The orphan/db-only diff is reported but **not auto-resolved** — by design (Chunk A is detection-only). Operator/Chunk-B owns remediation.
* `get_open_orders()` returns the account-wide open set, which includes
  complete-set-arb legs. Those that are correctly DB-open count as `in_sync`;
  only a genuinely orphaned one would page. No special-casing — acceptable, and
  noted for SENTINEL.
* Hermetic tests fake the asyncpg pool and CLOB client (consistent with the
  WARP-72 dataset suite and the lifecycle suite). No live broker call is exercised
  here; live behaviour rides on the existing, already-validated `ClobAdapter
  .get_open_orders` / `_signed_request` path.
* Full-repo `pytest` collection still shows the pre-existing environmental
  collection errors (missing `fastapi`/`apscheduler`/`web3` in the sandbox) unrelated to this change; the new suite imports cleanly and runs.

## 6. What is next

* WARP•SENTINEL MAJOR validation of this lane (execution/order-surface tier,
  detection-only).
* On merge → **Chunk B (kill-switch broker cancel-all)** on a separate
  `WARP/ROOT/kill-switch-cancel-all` branch: wire `ClobAdapter.cancel_all_orders`
  into `domain/risk/kill_switch_exec.execute_kill_switch`, gated by
  `USE_REAL_CLOB` + `ENABLE_LIVE_TRADING`, fail-soft, audited — so a kill cancels
  resting orders at the broker, not just DB-marks pending. (Today
  `execute_kill_switch` only does `UPDATE orders SET status='cancelled' WHERE
  status='pending'` and never tells the broker.)
* Operator, to activate telemetry in paper/live: the sweep is registered + ON by
  default but self-skips while `USE_REAL_CLOB=False`. Once a real broker session
  is live, orphan/drift detection begins automatically; flip
  `RECONCILE_LIVE_ORDERS_ENABLED=False` to unregister without a redeploy.
