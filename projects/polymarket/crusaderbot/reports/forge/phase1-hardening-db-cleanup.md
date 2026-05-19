# WARP•FORGE REPORT — phase1-hardening-db-cleanup

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: Signal freshness gate (step 1c coverage) + SSE reliability audit (Fly.io) + DB migrations 030/031/041 applied to Supabase production
Not in Scope: Fly.io redeploy trigger, live trading activation, WS fills path (separate lane), new feature work
Suggested Next Step: WARP🔹CMD review required. Tier: STANDARD.

---

## 1. What Was Built

### Signal Integrity Gate (WARP-30 Task 1)

The 30-minute freshness filter (`_MAX_SIGNAL_AGE_SECONDS = 1800`) was already
implemented at step 1c of `_process_candidate()` in a prior lane
(WARP/CRUSADERBOT-SIGNAL-FRESHNESS-GATE-CLEAN). This lane confirms it is in
place and adds 4 hermetic test cases covering the gate:

- `test_process_candidate_skips_stale_publication_signal` — signal 1801s old with
  pub_uuid is dropped before the trade engine is reached.
- `test_process_candidate_allows_fresh_publication_signal` — signal 60s old
  proceeds normally through the gate.
- `test_process_candidate_freshness_gate_skips_exact_boundary` — confirms the
  boundary condition (1800s is NOT `> 1800`, so the gate does not fire at exactly
  threshold).
- `test_process_candidate_freshness_gate_bypassed_for_lib_strategy` — lib-strategy
  candidates (pub_uuid=None) bypass the gate entirely, even with epoch-old signal_ts,
  because they always carry fresh runtime prices.

### SSE Reliability Audit (WARP-30 Task 2)

Full read of `webtrader/backend/sse.py`. Findings:

**PASS — production-ready for Fly.io:**

| Check | Result |
|---|---|
| Dedicated asyncpg connection (not pool) | PASS — LISTEN/NOTIFY requires persistent conn |
| Supabase Supavisor pooler normalization | PASS — `_normalize_dsn_for_listen` rewrites port 6543→5432 and pooler hostname→`db.<ref>.supabase.co` |
| SELECT 1 health probe every 15s | PASS — detects silent TCP drop without OS notification |
| Reconnect with exponential backoff | PASS — 1s initial, doubles to 60s cap |
| CancelledError handled cleanly | PASS — connection closed on task cancel |
| Per-user queue maxsize=100 | PASS — prevents memory bloat; QueueFull silently dropped |
| Ping every 25s (Fly.io idle timeout guard) | PASS — Fly.io idle closes at 60s; 25s is adequate |
| Event bus bridge (position.opened/closed/scanner.tick) | PASS — registered at startup |
| Broadcast channels for system/alerts | PASS — fan-out to all active sessions |
| Reverse map telegram_id→user_id (avoids DB per-event) | PASS — DB fallback on cache miss |

**Known limitation (pre-existing, not introduced here):**
`asyncio.get_event_loop().create_task(...)` in the fill-user resolution path
(line 133) is deprecated Python 3.10+. Low priority — does not affect
correctness in the current Fly.io deploy. Deferred to a cleanup lane.

### DB Migration Cleanup (WARP-30 Task 3)

All three migrations applied to Supabase production (`ykyagjdeqcgcktnpdhes`):

| Migration | Action | Result |
|---|---|---|
| 030_job_runs_metadata | `ADD COLUMN IF NOT EXISTS metadata JSONB` on `job_runs` | APPLIED — column confirmed present |
| 031_signal_scanner_user_enrollment | Re-seed feeds, enroll users, align access_tier | APPLIED — 6/6 users enrolled in signal_following, 6/6 subscribed to demo feed, 0 users below tier3. Live feed exists with custom UUID (slug unique constraint correctly guarded ON CONFLICT DO NOTHING) |
| 041_positions_strategy_type | `ADD COLUMN IF NOT EXISTS strategy_type VARCHAR(50)` + `market_question TEXT` on `positions` | APPLIED — both columns confirmed present |

---

## 2. Current System Architecture

Signal pipeline (unchanged):

```
signal_publications (feed)
    |
    v
signal_scan_job._process_candidate()
    |
    +-- step 0: crash-recovery stale-queued resume
    +-- step 1a: publication_already_queued dedup
    +-- step 1b: open position market check
    +-- step 1c: FRESHNESS GATE (_MAX_SIGNAL_AGE_SECONDS=1800)
    |       pub_uuid is not None AND age > 1800s → return (skipped_signal_stale)
    |       pub_uuid is None (lib-strategy) → bypass gate
    +-- step 2: market lookup
    +-- step 2b: target price drift guard
    +-- ...
    +-- step 10: TradeEngine.execute()
```

SSE pipeline (unchanged):

```
Supabase NOTIFY (cb_orders/fills/positions/settings/system/portfolio/alerts)
    |
    v
sse._listen_loop (dedicated asyncpg conn, direct port 5432)
    |-- SELECT 1 health probe every 15s
    |-- exponential backoff reconnect (1s→60s)
    v
_put_event → per-user asyncio.Queue (maxsize=100)
    |
    v
stream_for_user (SSE generator, 25s ping)
    |
    v
EventSourceResponse → WebTrader browser
```

DB schema additions applied:

```
job_runs         + metadata JSONB          (migration 030)
positions        + strategy_type VARCHAR   (migration 041)
positions        + market_question TEXT    (migration 041)
signal_feeds     + crusaderbot-demo feed   (migration 031, was already present)
signal_feeds     + crusaderbot-live feed   (migration 031, custom UUID, slug-unique)
user_strategies  all 6 users enrolled      (migration 031)
user_signal_subscriptions all 6 subscribed (migration 031)
```

---

## 3. Files Created / Modified

Modified:

- `projects/polymarket/crusaderbot/tests/test_signal_scan_job.py`
  Added 4 signal freshness gate tests at end of file (lines 726–839).

No production code changed — gate was already implemented; migrations applied
directly to Supabase via MCP.

---

## 4. What Is Working

- Signal freshness gate: 4 test cases added, all syntactically valid (AST parse
  clean). Runtime environment (Docker-based CI) required for full execution —
  container dep conflicts prevent local run in the cloud agent environment
  (pre-existing limitation: Rust cryptography bindings conflict).
- SSE: audit PASS across all 10 reliability checks. No code changes required.
- Migrations 030, 031, 041: all applied and verified via post-migration SQL checks.
  Columns confirmed on `job_runs` and `positions`; feeds confirmed in `signal_feeds`;
  user enrollment and subscription confirmed 6/6.

---

## 5. Known Issues

- SSE `asyncio.get_event_loop().create_task(...)` in fill-user resolution is
  deprecated Python 3.10+. Pre-existing, no capital impact. Deferred.
- Live feed seeded with custom UUID `55ccb726-a728-4c59-865f-32ff8dbd81ee` (not
  the canonical `00000000-0000-0000-0002-000000000001` from migration 031). This
  is correct — the slug `crusaderbot-live` already existed. No code references
  the canonical UUID hardcoded; all feed lookups use slug or operator_id.
- 4 freshness gate tests require Docker CI for runtime verification (dep issue in
  cloud agent). Tests follow established project patterns and pass AST parse.

---

## 6. What Is Next

WARP🔹CMD review required.
Source: `projects/polymarket/crusaderbot/reports/forge/phase1-hardening-db-cleanup.md`
Tier: STANDARD

After review:
- Fly.io redeploy to pick up schema changes (030/041 columns now live in DB).
- WARP🔹CMD decision: verify test suite in Docker CI (648+ hermetic tests).
- Follow-up deferred: fix `asyncio.get_event_loop().create_task` in sse.py.
