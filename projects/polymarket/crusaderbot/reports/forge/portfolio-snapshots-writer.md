# WARP•FORGE REPORT — portfolio-snapshots-writer

**Branch:** WARP/portfolio-snapshots-writer
**Issue:** #1245 (WARP-52 — portfolio_snapshots Python writer / cb_portfolio NOTIFY wiring)
**Date:** 2026-05-21 11:49 Asia/Jakarta
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** A new `portfolio_snapshots` row is INSERTed after every `paper.close_position` realised close and on each scheduler tick (60s) for users with paper activity, so the `cb_portfolio` NOTIFY trigger (migration 029, line 172-175) becomes live and WebTrader SSE listeners receive equity/PnL events.
**Not in Scope:** Live trading paths, schema changes to `portfolio_snapshots`, frontend SSE client work, retiring `services/portfolio_chart.py` ledger-derived chart (kept as-is — both paths coexist intentionally).

---

## 1. What Was Built

A best-effort, asyncio-safe writer that lights up the previously dormant `cb_portfolio` NOTIFY channel surfaced as the WARP-46 §5 advisory in `projects/polymarket/crusaderbot/reports/forge/runtime-spine-validation.md` (lines 109-114).

Three integration moves:

1. New module `projects/polymarket/crusaderbot/services/portfolio_snapshots.py` containing `write_snapshot(user_id)` (single-user) and `snapshot_active_users(lookback_hours=24)` (scheduler fan-out). The metrics SELECT runs entirely server-side in one round-trip — balance from `wallets`, equity = balance + per-position mark-to-market over open `positions`, `pnl_today` from `ledger` since Asia/Jakarta day start, `pnl_7d` from `ledger` over 7 days, `open_positions` count. The INSERT is the trigger source — `_cb_notify_portfolio_snapshots` (migration 029 line 115-128) emits the `cb_portfolio` payload as a side effect.

2. Inline call from `domain/execution/paper.py:close_position` immediately after the close transaction commits and after the audit write. Wiring sits OUTSIDE the DB transaction so a snapshot outage cannot poison the realised-close return contract. Both call sites that exercise paper close — the exit watcher (`scheduler.py:check_exits` → `exit_watcher.run_once` → `paper.close_position`) and the manual close handlers (`bot/handlers/my_trades.py:48` + `bot/handlers/trades.py:246`) — pick up the snapshot automatically because the wire lives inside `close_position` itself.

3. New APScheduler job `portfolio_snapshots` registered in `scheduler.py` at the standard interval (`PORTFOLIO_SNAPSHOT_INTERVAL = 60s`, added to `config.py`). The tick discovers users with either a ledger entry in the last 24 h OR an open position, then writes one snapshot per active user. Job is registered with `max_instances=1, coalesce=True` so a stalled tick cannot stack queue depth.

The writer is structurally safe: every exception is caught, logged at WARNING via `logger` (stdlib) plus a structured `log.info` success line via `structlog`. No exception path raises into either `paper.close_position` or the APScheduler `executed` callback, so a Postgres hiccup cannot crash either lane.

---

## 2. Current System Architecture (Slice Relevant to WARP-52)

```
realised close path (per trade)
  exit_watcher tick (30s)
    -> scheduler.py:335  check_exits
    -> domain/execution/exit_watcher.py:run_once
    -> domain/execution/paper.py:96  close_position
         UPDATE positions / ledger.credit_in_conn  (atomic txn)
         audit.write(paper_close)
       (NEW) -> services/portfolio_snapshots.write_snapshot(user_id)
                INSERT INTO portfolio_snapshots(user_id, balance, equity,
                                                pnl_today, pnl_7d, open_pos)
                  -> trg_cb_portfolio_snapshots AFTER INSERT
                  -> pg_notify('cb_portfolio', {event, user_id, id})
                  -> WebTrader SSE per-user channel

manual close path
  bot/handlers/my_trades.py / trades.py
    -> paper.close_position (same wiring above)

heartbeat path (per 60s)
  scheduler.py:add_job(snapshot_portfolios, interval=60s)
    -> services/portfolio_snapshots.snapshot_active_users()
       SELECT users with ledger<24h OR open positions
       -> write_snapshot per user (one INSERT each)
       -> cb_portfolio NOTIFY for each
```

This is additive only — the existing equity chart path (`services/portfolio_chart.py:38 _fetch_daily_balance_series`) is untouched and remains the canonical historical-chart source. The snapshot table now becomes the live-push source for SSE, while the ledger remains the cumulative-history source for the chart PNG.

---

## 3. Files Created / Modified

Created:

- `projects/polymarket/crusaderbot/services/portfolio_snapshots.py`
- `projects/polymarket/crusaderbot/tests/test_portfolio_snapshots_writer.py`

Modified:

- `projects/polymarket/crusaderbot/domain/execution/paper.py` — added `portfolio_snapshots` import and one `await portfolio_snapshots.write_snapshot(position["user_id"])` after the audit write in `close_position`.
- `projects/polymarket/crusaderbot/scheduler.py` — added `portfolio_snapshots` import, new `snapshot_portfolios()` job entry point, and `sched.add_job(snapshot_portfolios, "interval", seconds=s.PORTFOLIO_SNAPSHOT_INTERVAL, id="portfolio_snapshots", max_instances=1, coalesce=True)`.
- `projects/polymarket/crusaderbot/config.py` — added `PORTFOLIO_SNAPSHOT_INTERVAL: int = 60` to `Settings`.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — WARP-52 status moved from dispatched to delivered; KNOWN ISSUES advisory replaced with the resolution line.
- `projects/polymarket/crusaderbot/state/WORKTODO.md` — WARP-52 checkbox marked done.
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — lane closure entry appended.

No schema changes. No risk constant changes. No new external dependency.

---

## 4. What Is Working

Evidence (file:line for every claim):

- New writer module exports `write_snapshot` (single user) and `snapshot_active_users` (scheduler tick). See `services/portfolio_snapshots.py:103` (`async def write_snapshot`) and `services/portfolio_snapshots.py:144` (`async def snapshot_active_users`).
- `paper.close_position` invokes the writer immediately after `audit.write` returns and before the function's success return. See `domain/execution/paper.py:139` (`await portfolio_snapshots.write_snapshot(position["user_id"])`). The call sits AFTER `async with conn.transaction()` exits — the txn has already committed.
- The writer never raises into the trade-close path. See the `except Exception as exc:` at `services/portfolio_snapshots.py:130` (write_snapshot) and `services/portfolio_snapshots.py:178` (snapshot_active_users) — both return `None`/`0` and log at WARNING.
- Scheduler tick is registered. See `scheduler.py:564` (`sched.add_job(snapshot_portfolios, "interval", seconds=s.PORTFOLIO_SNAPSHOT_INTERVAL, id="portfolio_snapshots", max_instances=1, coalesce=True)`). Tick entry point at `scheduler.py:352` (`async def snapshot_portfolios`).
- Config knob exposed. See `config.py:189` (`PORTFOLIO_SNAPSHOT_INTERVAL: int = 60`). pydantic-settings ingests the env override `PORTFOLIO_SNAPSHOT_INTERVAL=...` automatically per the existing `Settings` pattern.
- `cb_portfolio` NOTIFY trigger fires on every INSERT — verified structurally against migration 029. See `projects/polymarket/crusaderbot/migrations/029_webtrader_tables.sql:115-128` (`_cb_notify_portfolio_snapshots`) and `:172-175` (`trg_cb_portfolio_snapshots AFTER INSERT ON portfolio_snapshots`). The trigger needs no Python code — the INSERT itself drives it.

Regression tests added in `tests/test_portfolio_snapshots_writer.py` (7 cases, all hermetic, all pass):

- `test_write_snapshot_inserts_row_and_returns_id` — happy path, asserts `INSERT INTO portfolio_snapshots` is the executed SQL, and all six metric values reach the INSERT in the right column order.
- `test_write_snapshot_skips_when_user_has_no_wallet` — unknown user (no wallet row): returns `None`, no INSERT.
- `test_write_snapshot_swallows_db_errors` — `get_pool()` raises: writer returns `None` (never re-raises into trade-close path).
- `test_snapshot_active_users_writes_one_per_active_user` — scheduler tick: pulls 3 users, calls `write_snapshot` 3 times, counts only the 2 successes.
- `test_snapshot_active_users_swallows_top_level_errors` — scheduler tick crash protection.
- `test_paper_close_position_invokes_snapshot_writer` — primary acceptance criterion: `paper.close_position(...)` calls `portfolio_snapshots.write_snapshot(user_id)` exactly once with the closer's user_id when the close UPDATE actually fires.
- `test_paper_close_skip_already_closed_does_not_snapshot` — idempotent-close branch (UPDATE matched zero rows): no spurious snapshot for an already-closed position.

Test run output (local hermetic suite):

```
projects/polymarket/crusaderbot/tests/test_portfolio_snapshots_writer.py
.......                                                                  [100%]
7 passed in 0.28s

projects/polymarket/crusaderbot/tests/test_exit_watcher.py
...............................                                          [100%]
31 passed in 10.51s
```

`py_compile` passes on all four touched production files (`portfolio_snapshots.py`, `paper.py`, `scheduler.py`, `config.py`).

---

## 5. Known Issues

- The metrics SQL computes `pnl_today` using `date_trunc('day', NOW() AT TIME ZONE 'Asia/Jakarta') AT TIME ZONE 'Asia/Jakarta'`, matching the project's Jakarta-day convention. The existing `wallet/ledger.py:83 daily_pnl` uses `date_trunc('day', NOW())` (UTC) instead. Behaviour is intentionally consistent with the WebTrader chart semantics (also Jakarta-anchored at `services/portfolio_chart.py:34 _today_jakarta`); divergence from `ledger.daily_pnl` is preserved on purpose — not converged in this lane to keep scope minimal.
- `snapshot_active_users` discovers active users by joining `users` to `ledger` (24h window) + `positions` (open). On a multi-thousand-user table during heavy market hours this is a few hundred rows per tick — well within the 60s budget. If user growth pushes scan latency past 5 s, the tick should be reshaped into a batched cursor (out of scope for this lane).
- No frontend changes — the WebTrader SSE client (`webtrader/frontend/...`) is already subscribed to `cb_portfolio` per WARP-46 evidence, so the channel becoming live should be invisible from a UI-code perspective. Manual smoke against the deployed bot would confirm end-to-end, but is not feasible from the cloud execution environment (issue #1243 same caveat).
- Heartbeat job writes one snapshot per active user even when nothing changed. This is by design — keeps the NOTIFY channel warm for SSE — but it does grow `portfolio_snapshots` linearly with `active_users × ticks_per_day`. A retention/pruning lane should follow once volume is observed in production. Out of scope here.

---

## 6. What Is Next

Suggested next step: WARP🔹CMD review and merge. Tier STANDARD → WARP•SENTINEL is NOT required per AGENTS.md routing.

Post-merge sequence:

1. Bot redeploy on Fly.io (no migration needed — migration 029 already applied in production per PROJECT_STATE line 2).
2. Operator should expect a `portfolio_snapshots` row roughly every 60 s per active user once the new job ticks. Verification: `SELECT COUNT(*) FROM portfolio_snapshots WHERE snapshot_at >= NOW() - INTERVAL '5 minutes';` after deploy.
3. Optional: confirm SSE receives `cb_portfolio` events via the WebTrader devtools network tab — the channel should fire on trade close and at the 60 s heartbeat.

Follow-up lanes (NOT this lane):

- Retention policy for `portfolio_snapshots` (keep N days, prune older). Required only once production volume is measured.
- Optional: drop the parallel ledger-derived chart path (`services/portfolio_chart.py`) and source the chart from `portfolio_snapshots` instead. Keeps the system to one source of truth for equity history. WARP🔹CMD decision.
- Optional convergence with `wallet/ledger.py:daily_pnl` on Jakarta-day semantics for cross-lane consistency. Currently divergent on purpose; flag here so a future lane can decide.

---

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : portfolio_snapshots row written after paper.close_position + every 60 s scheduler tick; cb_portfolio NOTIFY trigger fires automatically on each INSERT
Not in Scope      : Live trading paths, schema changes, frontend SSE client, retiring ledger-derived chart, retention/pruning of snapshot table
Suggested Next    : WARP🔹CMD review
