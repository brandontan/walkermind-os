# WARP•FORGE REPORT — heisenberg-556-realtime-trades

Branch: `WARP/ROOT/heisenberg-556-realtime-trades`
Role: WARP•R00T
Validation Tier: STANDARD
Claim Level: FOUNDATION
Validation Target: agent 556 client + sync job + buffer table — populated state only, no consumer wiring yet
Not in Scope: copy-trade fast-track consumer (separate follow-up lane after field-name shapes confirmed against prod), wallet 360 + leaderboard integration, scanner integration
Suggested Next Step: WARP🔹CMD review + merge → apply migration 070 to Supabase → set `HEISENBERG_REALTIME_TRADES_ENABLED=true` in Fly secrets after observing one tick's log shape via a brief dry-run.

---

## 1. What was built

Foundation lane for Heisenberg agent 556 (real-time trades). The Falcon UI
documents 556 as the agent that surfaces per-wallet fresh trades sub-minute —
complementary to the 30-minute leaderboard cycle (agent 584). Building this
agent into the bot enables a future copy-trade fast-track lane: instead of
waiting up to 30 minutes for a top trader's new entry to surface via the
leaderboard, the copy-trade monitor can react to fresh trades within ~60s.

This lane intentionally ships **only the buffer plumbing** — no consumer
wires it yet, because the upstream field-name contract for 556 is unconfirmed
(consistent with how 574/575/568/585 were originally shipped — defensive field
aliasing on assumed names). Once a single production tick is observed and the
field shape is verified, a tiny follow-up lane wires copy_trade.monitor to read
the buffer.

Components:

1. **`services/heisenberg_trades.py`** — async client `fetch_recent(window_seconds, limit)`
   that hits the Falcon parameterized-retrieval endpoint with `agent_id=556`.
   Returns `[]` on token-unset / HTTP error / timeout — never raises.
   Defensive field aliasing tolerates 3 plausible upstream conventions:
   `wallet`/`proxy_wallet`/`address`/`trader`, `condition_id`/`conditionId`/
   `market_id`/`marketId`, `side`/`direction`/`outcome`, `trade_time`/
   `timestamp`/`ts`/`created_at`. ISO-8601 + epoch (int and string) timestamps
   both parsed. Bad rows surface as a single WARNING with sample keys so a
   field-name drift is visible in logs instead of producing silent empty rows.
   Returns typed `RealtimeTrade` dataclass.

2. **`jobs/heisenberg_realtime_sync.py`** — scheduled job (`JOB_ID =
   "heisenberg_realtime_trades_sync"`) that on each tick:
   - Calls `fetch_recent(window=300s, limit=200)`.
   - Upserts each trade into `heisenberg_realtime_trades` keyed on
     `(wallet, condition_id, trade_time, side)` — dedup-safe across overlapping
     poll windows.
   - Prunes rows older than `HEISENBERG_REALTIME_TRADES_RETENTION_HOURS`
     (default 24h).
   - Never raises; logs warnings on every failure path.

3. **`migrations/070_heisenberg_realtime_trades.sql`** — buffer table +
   3 indexes (dedup unique, wallet-time DESC for consumer lookups,
   fetched_at for the retention sweep). RLS enabled deny-by-default
   (parity with mig 046 / strategies / account_link_codes).

4. **Config knobs** (4 new in `config.py`):
   - `HEISENBERG_REALTIME_TRADES_ENABLED: bool = False` — **DEFAULT OFF**
   - `HEISENBERG_REALTIME_TRADES_INTERVAL_SEC: int = 60`
   - `HEISENBERG_REALTIME_TRADES_WINDOW_SEC: int = 300`
   - `HEISENBERG_REALTIME_TRADES_RETENTION_HOURS: int = 24`

5. **Scheduler** — registers `run_job` at `interval=INTERVAL_SEC` only when
   `HEISENBERG_REALTIME_TRADES_ENABLED=True`. Job itself still re-checks
   `HEISENBERG_API_TOKEN` per tick (defence-in-depth for staged rollouts
   where the flag is on but the token hasn't been provisioned yet — the
   client returns `[]` so the job is a clean no-op).

Triple-gated rollout posture:
- env: `HEISENBERG_API_TOKEN` set (shared with 574/575/568/585/584/581 — now
  live in prod via the earlier `fly secrets set`).
- config: `HEISENBERG_REALTIME_TRADES_ENABLED=true` (default OFF in source).
- scheduler: `max_instances=1` + `coalesce=True` prevents overlap on a slow tick.

---

## 2. Current system architecture

```text
Heisenberg agent 556 (real-time trades, Falcon API)
        │
        │  jobs/heisenberg_realtime_sync.run_job() — every 60s when flag ON
        │
        ├─► services/heisenberg_trades.fetch_recent(window=300s, limit=200)
        │       │
        │       ├─► HTTP POST /api/v2/semantic/retrieve/parameterized
        │       │      body = { agent_id: 556, params: {lookback_seconds: "300"}, … }
        │       │
        │       ├─► HEISENBERG_API_TOKEN unset → return []  (no-op)
        │       ├─► HTTP error / timeout       → log WARNING + return []
        │       └─► bad shape (missing wallet/cid/side/time) → drop row + WARNING
        │
        ├─► UPSERT INTO heisenberg_realtime_trades
        │       ON CONFLICT (wallet, condition_id, trade_time, side)
        │       DO UPDATE SET (price, size_usdc, raw, fetched_at)
        │
        └─► DELETE rows WHERE fetched_at < NOW() - RETENTION_HOURS
                (skipped when retention=0)

heisenberg_realtime_trades  ← DORMANT until follow-up consumer lane
        │
        ▼
[ future: copy_trade.monitor sub-minute fast-track ]
        │
        ▼
copy_trade_tasks  →  mirror execution
```

No existing trading code reads from `heisenberg_realtime_trades` yet. This
ship preserves every prior behaviour and adds an additive observable surface.

---

## 3. Files created / modified

Created:
- `projects/polymarket/crusaderbot/services/heisenberg_trades.py`
- `projects/polymarket/crusaderbot/jobs/heisenberg_realtime_sync.py`
- `projects/polymarket/crusaderbot/migrations/070_heisenberg_realtime_trades.sql`
- `projects/polymarket/crusaderbot/tests/test_heisenberg_realtime_trades.py`
- `projects/polymarket/crusaderbot/reports/forge/heisenberg-556-realtime-trades.md` (this)

Modified:
- `projects/polymarket/crusaderbot/config.py` (4 new Settings fields)
- `projects/polymarket/crusaderbot/scheduler.py` (conditional `add_job` registration)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

---

## 4. What is working

- `pytest projects/polymarket/crusaderbot/tests/test_heisenberg_realtime_trades.py` → **13 passed**:
  - 5 client field-aliasing tests (canonical names; `proxy_wallet`/camelCase/
    `direction` aliases; missing-field rejection; bad-timestamp rejection;
    NaN/Infinity float rejection)
  - 2 client token-guard tests (empty token → `[]`; HTTP 500 → `[]`)
  - 1 job token-guard test (`(0, 0)` when token unset)
  - 3 job flow tests (upsert + prune happy-path with execute call shape pins;
    empty-trades-still-prunes; retention=0 skips prune)
  - 2 source-pin tests (config default OFF; JOB_ID string)
- Full suite: **1864 passed, 6 skipped, 0 failed** (1851 prior + 13 new).
- `python -m py_compile` clean on all 4 modified/created Python files.
- Scheduler audit: when `HEISENBERG_REALTIME_TRADES_ENABLED=False` (default),
  `add_job` for the new id is never called → no behaviour change in production.

---

## 5. Known issues

- **Field-name assumptions for agent 556 are unconfirmed**. The client uses
  defensive aliasing on plausible names — same approach 574/575/568/585 used at
  initial ship. If upstream uses entirely different field names, the
  `bad_trade` WARNING fires with sample keys so operator can adjust the alias
  list in `services/heisenberg_trades._normalise()`. Buffer table stays empty
  until aliases align, which is a safe failure mode.
- **No consumer wired yet**. The buffer table is populated but nothing reads
  it. Future lane `WARP/ROOT/copy-trade-realtime-fast-track` will wire
  `copy_trade.monitor.run_once` to consult this buffer alongside the existing
  leaderboard cycle. Shipping the consumer in the same lane would risk
  rolling back this foundation if a regression in the consumer needs revert —
  separating the two keeps the buffer a stable data source.
- **Migration 070 must be applied to Supabase before the flag is flipped**.
  Without the table, the upsert raises and the job logs a warning every tick
  but does no other harm.

---

## 6. What is next

- WARP🔹CMD review + merge.
- Apply migration 070 to Supabase (additive: new table + 3 indexes + RLS).
- Stage rollout:
  1. Set `HEISENBERG_REALTIME_TRADES_ENABLED=true` in Fly secrets for one
     deploy cycle, watch logs for one tick:
     - Expected good path: `heisenberg_realtime_sync: upserted=N pruned=M
       window=300s` with N > 0 within 10 minutes.
     - Field-drift path: `heisenberg_trades: N/M rows dropped — likely
       upstream field-name drift; sample keys=[…]`. Operator copies the keys
       into `_normalise()`, redeploys.
  2. After 1 hour of clean upserts, follow-up lane wires
     `copy_trade.monitor` to consult the buffer.
- Operator visual check after activation:
  - In Supabase: `SELECT COUNT(*), MIN(trade_time), MAX(trade_time),
    COUNT(DISTINCT wallet) FROM heisenberg_realtime_trades WHERE fetched_at >
    NOW() - INTERVAL '5 minutes';` — confirms live activity.

---

Validation Tier: **STANDARD** — additive foundation, default OFF, no existing
runtime path touched.
Claim Level: **FOUNDATION** — buffer populated only, no consumer.
Validation Target: client field aliasing + token guard + job upsert/prune
mechanics + scheduler conditional registration + migration shape.
Not in Scope: trading logic, copy-trade execution, risk gate, scanner.
Suggested Next Step: WARP🔹CMD review on the diff. MAJOR-tier SENTINEL not
required (foundation behind feature flag default OFF, no existing path
modified).
