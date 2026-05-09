# WARP•FORGE REPORT — order-lifecycle

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: ClobAdapter lifecycle surface + OrderLifecycleManager polling loop + APScheduler registration + DB migration 015 (orders columns + fills table)
Not in Scope: live router rewire to use lifecycle outputs (Phase 4D); ledger reversal on cancel/expiry (operator-driven for now); on-chain order schema reimplementation (still on py-clob-client OrderBuilder)
Suggested Next Step: WARP•SENTINEL validation required before merge

---

## 1. What Was Built

Phase 4C order lifecycle management:

- `ClobAdapter.post_order` now accepts `tick_size: Optional[str] = None`
  and `neg_risk: Optional[bool] = None`, threaded through
  `_build_signed_order` into `py_clob_client.OrderBuilder.create_order`
  via `CreateOrderOptions` (deferred from 4A).
- New `ClobAdapter` lifecycle methods:
  - `cancel_all_orders(market: Optional[str] = None)` — `DELETE
    /cancel-market-orders` if market is supplied, else `DELETE
    /cancel-all`. The Phase-4A `cancel_all()` is preserved as an alias.
  - `get_fills(order_id)` — `GET /data/trades?taker_order_id={id}`,
    normalises bare-list and `{"data": [...]}` envelope shapes to a
    plain `list[dict]`.
  - `get_open_orders(market=None)` — `GET /data/orders[?market=]`,
    same envelope normalisation.
- `MockClobClient` matches the new surface (cancel_all_orders /
  get_fills / get_open_orders / `record_fill` test helper) and now
  records `tickSize` + `negRisk` on every accepted order so callers
  can assert forwarding without a live broker.
- `ClobClientProtocol` widened to include the new methods so the live
  callers can swap `MockClobClient` and `ClobAdapter` interchangeably.
- New `domain/execution/lifecycle.py` —
  `OrderLifecycleManager`:
  - `poll_once()` selects every `mode='live'` order with status in
    (`'submitted'`, `'pending'`) and dispatches per-row.
  - Paper-mode shortcut: when `USE_REAL_CLOB=False`, the manager
    synthesises a `FILLED` outcome after the first poll cycle so
    dry-run rows do not accumulate. The DB write paths are identical
    to the live branch — the on-fill helper, `fills`-row insert and
    Telegram notification all run in paper mode.
  - Live-mode resolution: `client.get_order(broker_id)` ->
    normalise via `_broker_status` -> on FILLED also calls
    `client.get_fills(broker_id)` and aggregates the weighted
    average price.
  - Stale guard: after `ORDER_POLL_MAX_ATTEMPTS` (default 48) the
    order is marked `'stale'` and the operator is paged via
    `notifications.notify_operator`.
  - Per-order failure containment: a single broker hiccup is logged
    + counted but never aborts the rest of the sweep.
- `scheduler.py` registers a new APScheduler job `order_lifecycle`
  on the existing `AsyncIOScheduler` at boot, firing
  `poll_order_lifecycle()` every
  `ORDER_POLL_INTERVAL_SECONDS` (default 30s, `max_instances=1`,
  `coalesce=True`).
- `config.py` adds `ORDER_POLL_INTERVAL_SECONDS=30` and
  `ORDER_POLL_MAX_ATTEMPTS=48` to `Settings`.
- Migration `015_order_lifecycle.sql` (idempotent, additive):
  - `orders`: `filled_at`, `cancelled_at`, `expired_at`,
    `fill_price NUMERIC(10,6)`, `fill_size NUMERIC(18,6)`,
    `poll_attempts INTEGER NOT NULL DEFAULT 0`, `last_polled_at`.
  - Partial index `idx_orders_lifecycle_open` over
    `(status, last_polled_at NULLS FIRST)
    WHERE status IN ('submitted', 'pending')`.
  - New `fills` table — `order_id` FK + unique `fill_id` + price /
    size / side / timestamp + raw JSONB; two supporting indexes.
  - In-file rollback block (operator-executed via psql).

---

## 2. Current System Architecture

```
APScheduler (AsyncIOScheduler)
   |
   +-- order_lifecycle job (every ORDER_POLL_INTERVAL_SECONDS, default 30s)
         |
         v
   OrderLifecycleManager.poll_once()
         |
         +-- SELECT FROM orders WHERE mode='live'
         |     AND status IN ('submitted', 'pending')
         |
         |   per-row dispatch
         v
   _resolve_one()
         |
         +-- USE_REAL_CLOB=False
         |     after PAPER_FILL_AFTER_ATTEMPTS (=1)
         |       -> _on_fill (synthetic fill from order.price/size)
         |
         +-- USE_REAL_CLOB=True
               try get_clob_client() -> ClobClientProtocol
                 ClobConfigError / ClobAuthError -> log + abort sweep
               client.get_order(broker_id)
                 _broker_status -> filled / cancelled / expired / open
                   filled    -> client.get_fills + _on_fill
                   cancelled -> _on_cancel
                   expired   -> _on_expiry
                   open + attempts >= MAX -> _mark_stale
                   open + attempts <  MAX -> _touch (poll_attempts++)
```

Pipeline placement:
DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION (live.execute) →
**LIFECYCLE (this layer, pulls broker state back into DB)** →
MONITORING.

Side effects:

- `_on_fill`: UPDATE orders status='filled' + fill_price + fill_size +
  filled_at + last_polled_at; INSERT INTO fills (... ON CONFLICT
  (fill_id) DO NOTHING); UPDATE positions current_price; audit
  `order_filled`; Telegram fill alert to user.
- `_on_cancel` / `_on_expiry`: UPDATE orders to terminal status with
  the appropriate timestamp column; UPDATE positions to
  `status='cancelled'` if a position was opened off the order; audit
  `order_cancelled` / `order_expired`; Telegram alert to user.
- `_mark_stale`: UPDATE orders status='stale' with reason in
  error_msg; audit `order_stale`; Telegram **operator** alert.

---

## 3. Files Created / Modified

Modified:

- `projects/polymarket/crusaderbot/integrations/clob/adapter.py`
  `post_order` gains tick_size + neg_risk; `_build_signed_order`
  threads them through `CreateOrderOptions`; new
  `cancel_all_orders`, `get_fills`, `get_open_orders`; `cancel_all`
  preserved as alias.
- `projects/polymarket/crusaderbot/integrations/clob/mock.py`
  Mock parity for new methods; `tickSize` + `negRisk` recorded;
  `record_fill` test helper.
- `projects/polymarket/crusaderbot/integrations/clob/__init__.py`
  `ClobClientProtocol` widened.
- `projects/polymarket/crusaderbot/scheduler.py`
  Registers `order_lifecycle` job; new `poll_order_lifecycle`
  scheduler entry point.
- `projects/polymarket/crusaderbot/config.py`
  `ORDER_POLL_INTERVAL_SECONDS=30`,
  `ORDER_POLL_MAX_ATTEMPTS=48`.
- `projects/polymarket/crusaderbot/tests/test_clob_adapter.py`
  Stub fixture absorbs new tick_size/neg_risk kwargs via `**_kwargs`
  so existing 4A test count is preserved.

Created:

- `projects/polymarket/crusaderbot/migrations/015_order_lifecycle.sql`
  Idempotent ADD COLUMN IF NOT EXISTS for the seven order columns,
  CREATE TABLE IF NOT EXISTS for `fills`, partial + supporting
  indexes, in-file rollback block.
- `projects/polymarket/crusaderbot/domain/execution/lifecycle.py`
  `OrderLifecycleManager` + module-level `poll_once` shim +
  `_broker_status` / `_aggregate_fills` helpers.
- `projects/polymarket/crusaderbot/tests/test_order_lifecycle.py`
  24 hermetic unit tests (no DB / no network / no Telegram). 23
  collect green locally; 1 (`test_scheduler_registers_order_lifecycle_job`)
  uses `pytest.importorskip("web3")` so it skips locally and runs
  in CI where web3 is installed.
- `projects/polymarket/crusaderbot/reports/forge/order-lifecycle.md`
  This file.

Not modified (preserved):

- `domain/execution/live.py` — Phase 4B execute() / close_position()
  paths untouched. The lifecycle manager pulls from existing
  `orders` rows; it does not create them.
- `integrations/polymarket.py` — legacy SDK path remains dead-code
  in execution; cleanup deferred to
  `WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP`.

---

## 4. What Is Working

- `ClobAdapter.post_order(tick_size=..., neg_risk=...)` threads both
  values into `OrderBuilder.create_order` via `CreateOrderOptions`;
  the default branch (both `None`) is byte-for-byte identical to
  Phase 4A so existing callers are unaffected.
- `cancel_all_orders` routes correctly between scoped
  (`/cancel-market-orders`) and global (`/cancel-all`).
- `get_fills` and `get_open_orders` normalise both bare-list and
  `{"data": [...]}` envelope responses.
- `OrderLifecycleManager.poll_once`:
  - Paper mode: synthesises a fill after one cycle, writes the
    `fills` row, fires the user notification, and never invokes
    the CLOB factory (verified by injection assertion in tests).
  - Live mode FILLED: queries broker -> records weighted avg price
    + fills rows -> updates position current_price -> audit +
    Telegram.
  - Live mode CANCELLED / EXPIRED: terminal status update + open
    position rolled to `'cancelled'` + audit + Telegram.
  - Live mode OPEN: only `_touch` runs (poll_attempts++,
    last_polled_at = NOW()), no notifications, no audit.
  - Stale: after `ORDER_POLL_MAX_ATTEMPTS` poll cycles, row flips
    to `status='stale'`, operator alert fires.
  - CLOB factory failure: aborts the sweep with structured
    `errors` count rather than crashing the scheduler tick.
  - Race-loss: `UPDATE ... RETURNING id` returning NULL is
    detected and the on-fill / on-cancel paths bail without
    duplicate side effects.
- APScheduler `order_lifecycle` job registers on startup with
  `max_instances=1, coalesce=True` so backed-up ticks do not stack.
- Migration 015 is idempotent: re-running on a partially-applied
  schema is a no-op (every DDL guarded by `IF NOT EXISTS` /
  `ADD COLUMN IF NOT EXISTS`). Rollback block included.
- `USE_REAL_CLOB=False` default preserved — no real-broker traffic
  is ever generated by the lifecycle path in CI.
- `ENABLE_LIVE_TRADING` is **not** mutated, **not** read for
  activation, and **not** required by the lifecycle path. Activation
  posture remains PAPER ONLY for this PR.
- 23/23 hermetic lifecycle tests pass locally; 30/30 Phase 4A CLOB
  tests still green (no regression from the post_order signature
  change).
- Ruff clean on every file touched in this lane.

---

## 5. Known Issues

- `test_scheduler_registers_order_lifecycle_job` skips locally when
  `web3` is not installed (the scheduler imports
  `integrations/polygon.py` -> `web3` at module load). CI has
  `web3` installed and runs the assertion.
- pytest-asyncio emits 6 warnings about `pytestmark =
  pytest.mark.asyncio` being applied to sync helper tests
  (`_broker_status` / `_aggregate_fills` units). Cosmetic — matches
  the project's existing test-module convention (see
  `tests/test_clob_adapter.py`).
- Lifecycle manager does **not** credit the ledger back on
  cancel / expiry. The live `execute()` debits the ledger at
  position-insert time; rolling that back automatically risks
  double-credits on edge cases where the broker reports cancelled
  but a partial fill exists. Operator-driven reconciliation via
  `audit.log` rows (`order_cancelled` / `order_expired`) is the
  current contract; a follow-up
  `WARP/CRUSADERBOT-LIFECYCLE-LEDGER-REVERSAL` lane can wire the
  ledger credit once the cancel-vs-partial-fill semantics are
  audited end-to-end.
- `polymarket_order_id` missing on a row is handled defensively:
  the manager touches the row each cycle and marks it stale once
  the poll budget is spent rather than spamming the broker.

---

## 6. What Is Next

WARP•SENTINEL validation required:

- Source: `projects/polymarket/crusaderbot/reports/forge/order-lifecycle.md`
- Tier: MAJOR
- Scope: idempotency of migration 015; lifecycle dispatch
  correctness (filled/cancelled/expired/stale/open); paper-mode
  mock fill staying off the network; activation guard posture
  (PAPER ONLY — `ENABLE_LIVE_TRADING` and `USE_REAL_CLOB` remain
  NOT SET); APScheduler job registration and concurrency
  (`max_instances=1, coalesce=True`).

After SENTINEL APPROVED: WARP🔹CMD merge decision on this PR.
Post-merge candidates:
- `WARP/CRUSADERBOT-LIFECYCLE-LEDGER-REVERSAL` (MAJOR) — ledger
  credit on cancel/expiry.
- `WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP` (MINOR) — remove
  `_build_clob_client` from `integrations/polymarket.py`.
- `WARP/CRUSADERBOT-PHASE4D-ROUTER-LIFECYCLE` — surface
  lifecycle outputs (filled/cancelled events) to the router so
  callers can `await fill_confirmed` instead of trusting
  optimistic open-time inserts.
