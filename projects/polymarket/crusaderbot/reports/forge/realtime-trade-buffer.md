# WARP•FORGE Report — realtime-trade-buffer

Branch: WARP/realtime-trade-buffer
Role: WARP•R00T (system hardening — restore a capability killed by WARP-82 without durable storage)
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: an in-memory replacement for the dropped `heisenberg_realtime_trades` table; the producer (sync job) and both consumers (Sharp Money signal, copy-trade fast-track) read/write the buffer; no durable storage; feature flags untouched.
Not in Scope: enabling any feature flag (`HEISENBERG_REALTIME_TRADES_ENABLED` / `HEISENBERG_FAST_TRACK_ENABLED` stay operator-controlled); the live agent-556 API integration (unchanged); end-to-end runtime proof (requires the live token + flag ON in prod).
Suggested Next Step: WARP🔹CMD review → merge. To actually re-activate Sharp Money, the operator sets `HEISENBERG_REALTIME_TRADES_ENABLED=true` (+ `HEISENBERG_API_TOKEN`); the buffer then fills and the signal returns — with zero DB growth.

## 1. What was built

WARP-82 dropped `heisenberg_realtime_trades` (the #1 disk hog) and stubbed its
producer to log-only, which went dark for two consumers:
- `domain/playbook/sharp_flow.py` — the Sharp Money **signal** (read-only).
- `services/copy_trade/realtime_fast_track.py` — the copy-trade **execution**
  fast-track (gated `HEISENBERG_FAST_TRACK_ENABLED`, default OFF) — which still
  `SELECT`ed the now-dropped table (a latent break if ever enabled).

Per the operator ruling "real-time strategy data should use a temporary store, not
the durable DB", this lane introduces an **in-memory, per-process, time-windowed
trade buffer** and repoints the producer + both consumers at it. No table, no
migration, no DB growth.

- New `services/heisenberg_buffer.py`: bounded (`_MAX_ENTRIES=20_000`) dict keyed
  by the former UPSERT key `(wallet, condition_id, trade_time, side)`, with a 24h
  retention prune and a size-cap evict-oldest backstop. Reads: `trades_for_markets`
  (Sharp Money) and `trades_for_wallet` (fast-track). asyncio-only — every function
  is synchronous (no `await`), so on the single event loop a call is atomic; no lock,
  no threading.
- Producer `jobs/heisenberg_realtime_sync.py`: rewritten to `record_trades(...)`
  into the buffer; removed the dead DB `_prune` (referenced the dropped table) and
  the `get_pool` import.
- `sharp_flow.fetch_sharp_flows`: now one small query for the sharp-wallet set
  against the durable `leaderboard_stats`, then reads trades from the buffer and
  applies the identical `yes_accumulation_signed` directional aggregation in Python.
- `realtime_fast_track._process_wallet`: reads `trades_for_wallet` instead of
  `SELECT FROM heisenberg_realtime_trades`; watermark logic unchanged
  (`copy_trade_tasks.last_realtime_seen_at` stays durable).

## 2. Current system architecture

```
heisenberg agent 556 API ──(60s sync job)──► heisenberg_buffer  [in-memory, 24h TTL, ≤20k, dedup]
                                                   │
                       ┌───────────────────────────┴───────────────────────────┐
            sharp_flow.fetch_sharp_flows                       realtime_fast_track._process_wallet
            (leaderboard_stats sharp set [DB]                   (trades_for_wallet since watermark
             + trades_for_markets [buffer])                      → monitor._process_one)  [gated OFF]
```

Single Fly process runs producer + both consumers on one event loop, so the
in-memory buffer is shared without IPC. Reset-on-restart is acceptable: the sync
job refills within one tick; both readers are fail-soft (empty buffer → Sharp
Money abstains, fast-track finds nothing).

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/services/heisenberg_buffer.py`
- `projects/polymarket/crusaderbot/tests/test_heisenberg_buffer.py`

Modified:
- `projects/polymarket/crusaderbot/jobs/heisenberg_realtime_sync.py` — write to buffer; drop dead `_prune` + `get_pool`.
- `projects/polymarket/crusaderbot/domain/playbook/sharp_flow.py` — leaderboard set (DB) + trades (buffer).
- `projects/polymarket/crusaderbot/services/copy_trade/realtime_fast_track.py` — buffer read instead of SQL.
- `projects/polymarket/crusaderbot/tests/test_heisenberg_realtime_trades.py` — producer tests → buffer assertions (no get_pool).
- `projects/polymarket/crusaderbot/tests/test_playbook_sharp_money.py` — DB-backed section → leaderboard + buffer.
- `projects/polymarket/crusaderbot/tests/test_no_persistence_to_bloat_tables.py` — read-guard now also covers `heisenberg_realtime_trades`.

## 4. What is working

- `pytest test_heisenberg_buffer.py test_heisenberg_realtime_trades.py test_no_persistence_to_bloat_tables.py` → **28 passed** in the sandbox.
- `ruff` + `py_compile` clean on all touched files.
- Read-guard proves zero `FROM/JOIN job_runs|heisenberg_realtime_trades` SQL in production code.
- `test_playbook_sharp_money.py` (full sharp-flow aggregation, leaderboard scoping, non-sharp exclusion, fail-soft, zero-size skip) validates in CI — it needs `eth_account` (its `strategies/__init__` import chain), absent from the dep-light sandbox.

## 5. Known issues

- Buffer is **per-process and ephemeral** — on restart Sharp Money is blind until
  the sync job's next tick refills the lookback (a few ticks for a full 24h
  window). Acceptable per the no-durable-storage ruling; both readers fail-soft.
- 24h of trades held in memory (bounded ≤20k). At agent-556 volumes this is a few
  thousand entries — well within memory; the cap is a backstop only.
- **No behavior change until the operator enables it.** `HEISENBERG_REALTIME_TRADES_ENABLED`
  is still default-OFF, so the buffer stays empty and Sharp Money keeps abstaining
  until the operator flips the flag (+ provides `HEISENBERG_API_TOKEN`). The
  execution fast-track stays additionally gated by `HEISENBERG_FAST_TRACK_ENABLED`
  (default OFF) + kill-switch + 13-step risk gate + `ENABLE_LIVE_TRADING`.

## 6. What is next

- WARP🔹CMD review → merge.
- Operator (optional, to re-activate): set `HEISENBERG_REALTIME_TRADES_ENABLED=true`
  + `HEISENBERG_API_TOKEN`; confirm `/health` + logs show `heisenberg_realtime_sync`
  recording and `buffer_size` > 0; Sharp Money resumes claiming with no DB growth.
- The copy-trade execution fast-track remains a separate, deliberately-gated
  activation decision.
