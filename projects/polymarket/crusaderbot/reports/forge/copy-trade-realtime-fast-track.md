# WARP•FORGE REPORT — copy-trade-realtime-fast-track

Branch: `WARP/ROOT/copy-trade-realtime-fast-track`
Role: WARP•R00T
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: new fast-track consumer reads `heisenberg_realtime_trades` buffer + delegates to existing `monitor._process_one()`; watermark plumbing; conditional scheduler registration
Not in Scope: trading logic changes, risk gate, execution router, Polymarket integration, new buffer producer logic
Suggested Next Step: WARP🔹CMD review + merge → applied migration 071 → flip `HEISENBERG_FAST_TRACK_ENABLED=true` in Fly secrets once the buffer producer (lane 556) has logged a clean ≥10 min sample.

---

## 1. What was built

The Heisenberg agent 556 buffer (lane `WARP/ROOT/heisenberg-556-realtime-trades`,
already merged + deployed + verified populating at sub-minute latency) is now
consumed by a new fast-track copy-trade lane. Net effect: a leader wallet's
fresh trade flows to a subscriber's mirror evaluation in **~60s** instead of
the 5–10 min HTTP-polling latency of the existing wallet-watcher path.

Key design choice: the fast-track does NOT replace
`services/copy_trade/monitor.run_once()` — both paths coexist. Dedup via the
existing `copy_trade_idempotency (user_id, task_id, leader_trade_id)` table
guarantees a single execution per leader trade regardless of which path
discovers it first.

Components:

1. **`services/copy_trade/realtime_fast_track.run_once()`**
   - Same gates as the existing monitor (kill_switch + globally-disabled +
     active-tasks-only).
   - Groups active tasks by `wallet_address` so one buffer query covers every
     subscriber of a leader.
   - SELECTs FROM `heisenberg_realtime_trades` WHERE `wallet = $1 AND
     trade_time > $2 ORDER BY trade_time ASC`. The cutoff is the earliest
     watermark across all subscribers of that wallet (NULL → NOW() - 5 min
     fallback so first-tick after deploy catches recent buffer activity).
   - Per task: filters trades newer than that task's own watermark, then
     delegates to `monitor._process_one(task, raw_jsonb, wallet)` — the same
     function the slow leader-poller already drives. The `raw` JSONB has every
     field `_process_one()` reads (`id`/`side`/`outcome`/`condition_id`/
     `token_id`/`size`/`timestamp` — confirmed live via the buffer shape check
     in lane 556).
   - Per-task watermark UPDATE after dispatch
     (`GREATEST(COALESCE(last_realtime_seen_at, ts), ts)` so concurrent ticks
     never roll the watermark backward).
   - Top-level try/except: APScheduler never sees an unhandled exception.

2. **Migration 071 — `copy_trade_tasks.last_realtime_seen_at TIMESTAMPTZ`**
   - Additive, idempotent, applied to Supabase prod.
   - NULL semantics encoded in consumer: never run → look back 5 min.

3. **Model + repository plumbing**
   - `CopyTradeTask.last_realtime_seen_at: datetime | None = None`
   - `_SELECT` in `domain/copy_trade/repository.py` extended with the new
     column; `_row_to_task()` reads it with a `row.keys()` guard so legacy
     SELECTs that don't include the column still construct a valid task
     (defaults to None).

4. **Config knobs (2 new)**
   - `HEISENBERG_FAST_TRACK_ENABLED: bool = False` — **DEFAULT OFF**
   - `HEISENBERG_FAST_TRACK_INTERVAL_SEC: int = 30`

5. **Scheduler** — conditional `add_job` mirroring the agent 556 producer
   pattern (only registers when flag is on; `max_instances=1` +
   `coalesce=True` to prevent overlap).

Triple-gating posture:
- env: `HEISENBERG_API_TOKEN` (shared with all Heisenberg agents — live).
- config A: `HEISENBERG_REALTIME_TRADES_ENABLED=true` (producer side — already
  flipped on; buffer is populating sub-minute).
- config B: `HEISENBERG_FAST_TRACK_ENABLED=true` (consumer side — DEFAULT
  OFF; flip when ready).

Plus the four existing copy-trade safety gates apply unchanged:
- kill_switch (via existing monitor helpers)
- global copy_trade strategy on/off (via existing `_is_globally_disabled()`)
- per-user copy_trade_task status (filtered by `list_active_tasks()`)
- 13-step risk gate (inside `_process_one()` → TradeEngine pipeline)

---

## 2. Current system architecture

```text
Heisenberg agent 556  →  heisenberg_realtime_trades buffer  (lane 556, live)
                                  │
                                  │  every 30s when HEISENBERG_FAST_TRACK_ENABLED=true
                                  ▼
              services/copy_trade/realtime_fast_track.run_once()
                                  │
                                  ├─► kill_switch? globally disabled? → skip tick
                                  │
                                  ├─► list_active_tasks() (existing repo)
                                  │
                                  ├─► group by leader wallet
                                  │
                                  ├─► SELECT trades from buffer
                                  │     WHERE wallet=$1 AND trade_time > earliest_watermark
                                  │
                                  └─► per task × per fresh trade:
                                        ├─► monitor._process_one(task, raw_jsonb, wallet)
                                        │       │
                                        │       ├─► copy_trade_idempotency dedup check
                                        │       │   (same key as existing slow-poll path)
                                        │       │
                                        │       ├─► size scaler (existing)
                                        │       │
                                        │       ├─► 13-step risk gate (existing)
                                        │       │
                                        │       └─► paper or live mirror order
                                        │
                                        └─► UPDATE last_realtime_seen_at = max(trade_time)

In parallel (no change to existing path):
  services/copy_trade/monitor.run_once()  every 30s
        → wallet-watcher (Polymarket Data API HTTP poll)
        → SAME _process_one() with copy_trade_idempotency dedup
```

If a trade is buffered AND surfaces in the wallet-watcher response (which
will happen for every trade since both paths see the same upstream data),
the SECOND `_process_one()` call short-circuits at the idempotency check.
No duplicate mirror order.

---

## 3. Files created / modified

Created:
- `projects/polymarket/crusaderbot/services/copy_trade/realtime_fast_track.py`
- `projects/polymarket/crusaderbot/migrations/071_copy_trade_realtime_watermark.sql`
- `projects/polymarket/crusaderbot/tests/test_copy_trade_fast_track.py`
- `projects/polymarket/crusaderbot/reports/forge/copy-trade-realtime-fast-track.md` (this)

Modified:
- `projects/polymarket/crusaderbot/domain/copy_trade/models.py` (1 new field)
- `projects/polymarket/crusaderbot/domain/copy_trade/repository.py` (SELECT + row mapper)
- `projects/polymarket/crusaderbot/config.py` (2 new Settings fields)
- `projects/polymarket/crusaderbot/scheduler.py` (1 conditional `add_job`)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

---

## 4. What is working

- `pytest tests/test_copy_trade_fast_track.py` → **11 passed**:
  - 3 gate tests (kill_switch / globally_disabled / no_active_tasks → (0, 0))
  - 1 happy-path dispatch (2 fresh trades → 2 `_process_one` + watermark UPDATE
    to max trade_time)
  - 1 watermark filter test (older-than-cutoff trades skipped)
  - 1 NULL-watermark fallback test (uses NOW() - 300s window)
  - 1 failure-isolation test (one task's `_process_one` raises → other task
    still dispatches)
  - 1 buffer-fetch-failure never-raises guard
  - 3 source pins (JOB_ID, _INITIAL_LOOKBACK_SEC, config default OFF)
- Full suite: **1888 passed, 6 skipped, 0 failed** (1864 prior + 24 new from
  this lane and pre-existing tests).
- `python -m py_compile` clean on all 5 modified/created Python files.
- Scheduler audit: when `HEISENBERG_FAST_TRACK_ENABLED=False` (default),
  the new `add_job` is never called → zero production change post-merge.
- Migration 071 applied to Supabase prod (additive column, `ADD COLUMN
  IF NOT EXISTS`, no backfill needed).

---

## 5. Known issues

- The fast-track consumer relies on `agent 556`'s `raw` JSONB containing the
  full upstream payload. This was verified live via a one-off Supabase query
  on the live buffer in lane 556 — actual rows have `id`, `side`, `outcome`,
  `condition_id`, `token_id`, `size`, `timestamp`, `proxy_wallet`,
  `transaction_hash`. If upstream removes any of those fields, `_process_one`
  falls through its existing `.get()` defaults (no crash; trade may be
  silently skipped at the idempotency or size-extraction step).
- Concurrent dispatch race: if both the fast-track and the slow wallet-watcher
  call `_process_one()` for the same leader trade within milliseconds of each
  other, the second one short-circuits at the idempotency check
  (`ON CONFLICT DO NOTHING` on `copy_trade_idempotency`) — no duplicate
  mirror, but the second log line may report the trade as already-processed
  (expected, harmless).
- Watermark drift: a slow `_process_one()` doesn't block the next tick's
  fetch (max_instances=1 + coalesce — APScheduler skips the overlap). On a
  prolonged stall the watermark advances only on the most-recently-processed
  trade per task, which means a long pause could re-process up to 5 minutes
  of buffer on resume (idempotency table absorbs duplicates — no double
  executions, just CPU on the dedup check).

---

## 6. What is next

- WARP🔹CMD review + merge.
- Apply migration 071 to Supabase ✅ (already done via Supabase MCP).
- Stage rollout (operator):
  1. Verify buffer producer (lane 556) has logged ≥10 min of clean upserts.
  2. `fly secrets set HEISENBERG_FAST_TRACK_ENABLED=true -a crusaderbot`.
  3. Watch first tick log: `copy_trade_fast_track tick done tasks=N wallets=M
     scanned=X dispatched=Y`. dispatched > 0 within ~30s confirms end-to-end.
- Operator monitoring after activation:
  - In Supabase: `SELECT id, task_name, last_realtime_seen_at FROM
    copy_trade_tasks WHERE status='active' ORDER BY last_realtime_seen_at
    DESC NULLS LAST LIMIT 20;` — should show watermarks advancing within 60s
    of any leader trade.
  - In Sentry: watch for `copy_trade_fast_track` warning events; expected
    rate should be ≪ existing monitor's warning rate (cleaner data source).

---

Validation Tier: **STANDARD** — additive consumer behind a feature flag
default OFF; no existing copy-trade path modified; reuses existing
`_process_one()` so risk-gate + execution stays single-sourced.
Claim Level: **NARROW INTEGRATION** — wires a new data source into an
existing pipeline with no logic change to the pipeline itself.
Validation Target: gate behaviour, buffer fetch SQL, watermark update,
delegation to `_process_one()`, conditional scheduler registration,
default-OFF posture.
Not in Scope: trading logic, risk gate, execution router, Polymarket
integration, agent 556 producer (separate lane).
Suggested Next Step: WARP🔹CMD review on the diff. MAJOR-tier SENTINEL not
required — the consumer is dormant until the operator-flipped flag is on
AND the existing copy-trade gates + dedup remain the source of truth for
every mirror execution.
