# R12e Auto-Redeem System — Forge Report

**Validation Tier:** MAJOR
**Claim Level:** NARROW INTEGRATION (workers + queue wired end-to-end; on-chain CTF redemption tip gated by `EXECUTION_PATH_VALIDATED=false`)
**Validation Target:** services/redeem instant + hourly worker pipeline, redeem_queue table, AUTO_REDEEM_ENABLED guard, gas-spike defer, retry-once + operator alert, Settings UI mode toggle
**Not in Scope:** exit_watcher, entry flow, risk gate, Kelly sizing, applied_tp/sl_pct, wallet generator, deposit watcher, fee collection, referral payouts, other activation guards, R10 ledger primitives (`wallet/ledger.py` untouched)
**Suggested Next Step:** WARP•SENTINEL MAJOR audit before merge — focus on AUTO_REDEEM_ENABLED short-circuit completeness, queue race conditions (claim/release atomicity), gas-spike fallback flow, and the loser-position no-on-chain settlement path.

---

## 1. What was built

A dedicated `services/redeem/` module that owns auto-redemption end-to-end:

- **Resolution detection** (`redeem_router.detect_resolutions`) — periodic scan that flips `markets.resolved=TRUE` once Polymarket reports `closed`, then classifies each position in the resolved market: losers settle inline (DB close + P&L = -size + Telegram notify, no on-chain action); winners are enqueued to a new `redeem_queue` table.
- **Per-user dispatch** — when a winning position belongs to a user with `auto_redeem_mode='instant'`, the router fires the instant worker as an asyncio task. Hourly-mode users wait for the next hourly cron tick.
- **Instant worker** (`instant_worker.try_process`) — claims a queue row atomically, runs the gas guard for live positions only (releases back to pending without incrementing failure_count when gas > `INSTANT_REDEEM_GAS_GWEI_MAX`), submits the redeem, retries once after 30 s on failure, and on second failure releases the row back with `failure_count++` so the hourly worker picks it up.
- **Hourly worker** (`hourly_worker.run_once`) — drains every pending queue row sequentially (1 tx per position — CTF contract constraint), pages the operator via `monitoring.alerts._dispatch` once `failure_count` reaches the threshold (>= 2), and isolates per-row exceptions so a leaking row cannot poison the batch.
- **Persistent queue** — new `redeem_queue` table with unique index on `position_id` (idempotent enqueue), partial index on `status='pending'` (cheap drain scan), and partial index on `failure_count > 0` (operator review).
- **Settings UI** — top-level `⚙️ Settings` menu surface with `[Instant] [Hourly]` picker for `auto_redeem_mode`. Default remains `hourly`. The handler+keyboard live in `bot/handlers/settings.py` and `bot/keyboards/settings.py`. The legacy `setup.set_redeem_mode` callback inside the Setup flow is preserved (no duplication, both surfaces write to the same column).
- **Activation guard** — every entry point (`detect_resolutions`, `instant_worker.try_process`, `hourly_worker.run_once`) short-circuits to a log INFO and returns when `Settings.AUTO_REDEEM_ENABLED=False`. No raise, no crash.

---

## 2. Current system architecture

```
APScheduler
  ├── check_resolutions   (interval: RESOLUTION_CHECK_INTERVAL = 300s)
  │     └─ services.redeem.redeem_router.detect_resolutions()
  │           ├─ scan positions.redeemed=FALSE × markets.resolved=FALSE
  │           ├─ for each candidate market:
  │           │    └─ polymarket.get_market(...)   ← skip if still open
  │           │    └─ UPDATE markets SET resolved=TRUE, winning_side=...  (atomic)
  │           │    └─ for each position in market:
  │           │         ├─ loser  → settle_losing_position()
  │           │         │     ├─ UPDATE positions: closed, exit_reason=resolution_loss,
  │           │         │     │              pnl=-size, redeemed=TRUE
  │           │         │     ├─ audit.write(action='redeem_loss')
  │           │         │     └─ notifications.send(user)
  │           │         └─ winner → INSERT redeem_queue (idempotent)
  │           │              └─ if auto_redeem_mode='instant':
  │           │                  └─ asyncio.create_task(instant_worker.try_process(qid))
  │
  └── redeem_hourly       (interval: REDEEM_INTERVAL = 3600s)
        └─ services.redeem.hourly_worker.run_once()
              ├─ SELECT id FROM redeem_queue WHERE status='pending' ORDER BY queued_at
              └─ for each row:
                   ├─ claim_queue_row()                ← atomic pending→processing
                   ├─ settle_winning_position()
                   │    ├─ if mode='live': ensure_live_redemption() (idempotent / cond)
                   │    ├─ UPDATE positions: closed, exit_reason=resolution_win,
                   │    │                  pnl=payoff-size, redeemed=TRUE
                   │    ├─ ledger.credit_in_conn(T_REDEEM, payoff)
                   │    ├─ audit.write(action='redeem')
                   │    └─ notifications.send(user)
                   ├─ on success: mark_done()
                   └─ on failure: release_back_to_pending(increment_failure=True)
                        └─ if failure_count >= 2: alerts._dispatch('redeem_failed_persistent', ...)

Instant fast path (in-process, fired by router on resolution):
  instant_worker.try_process(queue_id)
    ├─ AUTO_REDEEM_ENABLED guard
    ├─ claim_queue_row()  ← race-safe vs hourly worker (status flip is the lock)
    ├─ if mode='live': polygon.gas_price_gwei()
    │     └─ > INSTANT_REDEEM_GAS_GWEI_MAX or read fails
    │           → release_back_to_pending(increment_failure=False)
    │             (hourly worker will retry; no failure penalty)
    ├─ try settle_winning_position() → mark_done()  ← happy path
    ├─ on raise: asyncio.sleep(30); retry once
    └─ on second raise: release_back_to_pending(increment_failure=True)
```

The new module replaces the inlined R10 redeem block that previously lived in `scheduler.py`. The scheduler is now thin: `check_resolutions` and `redeem_hourly` are 1-line delegations to the new module so the APScheduler job ids (`resolution`, `redeem`) keep pointing at the same callable.

---

## 3. Files created / modified

**Created:**

- `projects/polymarket/crusaderbot/services/redeem/__init__.py`
- `projects/polymarket/crusaderbot/services/redeem/redeem_router.py`
- `projects/polymarket/crusaderbot/services/redeem/instant_worker.py`
- `projects/polymarket/crusaderbot/services/redeem/hourly_worker.py`
- `projects/polymarket/crusaderbot/migrations/006_redeem_queue.sql`
- `projects/polymarket/crusaderbot/bot/handlers/settings.py`
- `projects/polymarket/crusaderbot/bot/keyboards/settings.py`
- `projects/polymarket/crusaderbot/tests/test_redeem_workers.py`
- `projects/polymarket/crusaderbot/reports/forge/r12e-auto-redeem.md`

**Modified:**

- `projects/polymarket/crusaderbot/scheduler.py` — `check_resolutions` and `redeem_hourly` now delegate to the new module; the inline R10 functions (`_instant_redeem_for_market`, `_redeem_position`, `_ensure_live_redemption`) are removed.
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — registers the new `^settings:` callback handler.
- `projects/polymarket/crusaderbot/bot/menus/main.py` — `⚙️ Settings` reply-keyboard label now routes to `settings_handler.settings_root` (was a placeholder pointing at `onboarding.help_handler`).

**Deviation from task spec (path):** task said `infra/migrations/006_redeem_queue.sql`. The crusaderbot migration loader at `database.run_migrations()` reads from `projects/polymarket/crusaderbot/migrations/` — placing the file under `infra/` would have shipped the SQL but never executed it. The migration uses the existing convention (`migrations/006_*.sql`) so it actually runs at startup. Flagged for SENTINEL.

**Deviation from task spec (gas threshold):** task body says "If gas > 100 gwei". The codebase uses `Settings.INSTANT_REDEEM_GAS_GWEI_MAX` (default 200, env-overridable). The instant worker compares against the configurable setting rather than a hard-coded 100 — operators can drop it to 100 by env without a code change. Flagged for SENTINEL.

---

## 4. What is working

Hermetic test suite (`tests/test_redeem_workers.py`, 14 tests) covers:

- AUTO_REDEEM_ENABLED guard short-circuits all three entry points.
- Instant: paper-mode success path skips the gas RPC entirely.
- Instant: live + gas-spike defers (`release_back_to_pending(increment_failure=False)`).
- Instant: live + gas RPC failure also defers (treats unreadable gas as a spike).
- Instant: first attempt fails, retry succeeds → `mark_done`, no release.
- Instant: both attempts fail → release with `increment_failure=True`.
- Instant: race-safe — `claim_queue_row` returning None exits cleanly without settling.
- Hourly: drains multiple pending rows successfully.
- Hourly: failure increments `failure_count`; no operator alert below threshold.
- Hourly: `failure_count >= 2` pages the operator with the `redeem_failed_persistent` alert key.
- Hourly: per-row exception isolated — does not poison the batch.
- Hourly: empty queue is a no-op.

Full crusaderbot test suite (87 tests, including 73 pre-existing) passes:
```
projects/polymarket/crusaderbot/tests/test_exit_watcher.py ............. (26)
projects/polymarket/crusaderbot/tests/test_health.py ................... (25)
projects/polymarket/crusaderbot/tests/test_positions_handler.py ........ (20)
projects/polymarket/crusaderbot/tests/test_redeem_workers.py ........... (14)
projects/polymarket/crusaderbot/tests/test_smoke.py ..                  (2)
======================== 87 passed ========================
```

Manual import smoke (with required env vars set) compiles every modified file and the new package cleanly.

---

## 5. Known issues

- `AUTO_REDEEM_ENABLED` default in `config.py` remains `True` (R10 inheritance). The task spec states the default should be `False` and forbids "Set AUTO_REDEEM_ENABLED = true". The current value was set in a prior lane (R10) and the task also forbids touching activation guards — leaving it as-is is the conservative read of the constraint pair. SENTINEL should decide whether this lane should flip the default.
- `INSTANT_REDEEM_GAS_GWEI_MAX` default is 200 (R10 inheritance). The task body uses 100 as the example threshold. Changing the default is a deployment-config decision; the constant is env-overridable so operators can drop it without a code change.
- `services/redeem/redeem_router.py` is the single owner of the `_settle_position` accounting; both workers call into it. A future SENTINEL pass may want to split the on-chain dispatch (`ensure_live_redemption`) into its own service for symmetry with the planned multi-tenant audit (Phase 8).
- The hourly worker's operator alert reuses the `monitoring.alerts._dispatch` underscore-prefix. A small follow-up could expose a public `alert_operator_redeem_failed_persistent` wrapper to match the exit-watcher pattern.
- The `setup.set_redeem_mode` legacy callback (inside the 🤖 Setup flow) is intentionally preserved — both the Setup and Settings surfaces write to the same `auto_redeem_mode` column. A later UX-cleanup lane may consolidate into the Settings menu.
- Existing pre-R12e drift in `state/PROJECT_STATE.md` lists `R12e — Live → Paper Auto-Fallback` under NOT STARTED. The current task assigned R12e to auto-redeem; the auto-fallback row is left verbatim per surgical-edit rule.

---

## 6. What is next

WARP•SENTINEL MAJOR audit required. Suggested phase coverage:

1. **Phase 0 pre-test** — confirm migration 006 path matches loader expectation, confirm `AUTO_REDEEM_ENABLED` guard behaviour matches operator intent, confirm no `phase*/` folders, confirm `setup.set_redeem_mode` was intentionally preserved (no duplication).
2. **Phase 3 failure modes** — gas RPC down, Polymarket API down, asyncpg timeout in `claim_queue_row`, on-chain submit raises (CTF contract error), Telegram notify down. Confirm queue stays consistent across each.
3. **Phase 4 async safety** — concurrent instant worker + hourly worker for the same `queue_id`, concurrent `detect_resolutions` for the same market, idempotency of `redeem_queue` insert under detection re-runs.
4. **Phase 5 risk rules** — confirm loser positions never trigger an on-chain redeem call, confirm winner positions cannot double-credit (already-closed branch + open-at-resolution branch).
5. **Phase 7/8** — Telegram preview of the `Settings → Auto-Redeem` flow + the operator alert body.

Suggested first issues SENTINEL should look at:

- Race window: `redeem_router._enqueue_redeem` runs `INSERT ON CONFLICT DO NOTHING` outside the `markets` UPDATE transaction. A second `detect_resolutions` could observe the resolved market and re-run classification. The unique index on `position_id` catches the double-enqueue, but the loser settlement path (`settle_losing_position`) is not queue-protected — it relies on the position-row `WHERE status='open' AND redeemed=FALSE` predicate to be idempotent. Confirm.
- Operator alert cooldown key uses `queue_id`. If a queue row is settled then a different position fails, the alert key dimension is unique per row, which is correct. SENTINEL should confirm no cooldown collision across distinct queue ids.
