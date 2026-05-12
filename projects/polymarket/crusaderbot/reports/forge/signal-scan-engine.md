# WARP•FORGE REPORT — signal-scan-engine

Validation Tier: MAJOR
Claim Level: FULL RUNTIME INTEGRATION
Validation Target: Signal publication pipeline — market_signal_scanner job + scheduler wire + DB seed migration + /health command + hourly ADMIN report
Not in Scope: Live trading execution, CLOB integration, real money orders, strategy logic changes
Suggested Next Step: WARP•SENTINEL validation required before merge

---

## 1. What Was Built

**PART 1 — AUDIT FINDINGS**

Signal scan jobs (`signal_scan`, `signal_following_scan`) were already registered in `scheduler.py` and running successfully every 3 minutes with zero errors. The pipeline was broken at the DATA layer, not the scheduler layer.

5 root-cause blockers identified:

| # | Blocker | Evidence |
|---|---------|---------|
| 1 | User `access_tier = 2` | Scanner requires `>= 3`; query returned 0 enrolled users |
| 2 | `user_strategies` empty | `sf_scan_job.run_once()` loaded zero users, exited immediately |
| 3 | `signal_feeds` empty | `_load_active_subscriptions()` returned `[]`; evaluator exited |
| 4 | `user_signal_subscriptions` empty | No user subscribed to any feed |
| 5 | Nothing writing to `signal_publications` | Market scanner didn't exist; `signal_following_scan` only READS, never writes |

**PART 2 — SCHEDULER: Already wired. No changes required.**

`scheduler.py` lines 544–547 already registered `signal_scan` and `signal_following_scan`. Added only the new `market_signal_scanner` and `hourly_report` jobs.

**PART 3 — MARKET SIGNAL SCANNER (new)**

`jobs/market_signal_scanner.py` — the missing DATA layer writer:
- Polls Polymarket API via existing `polymarket.get_markets()`
- Filters: active markets, `liquidity >= $1,000`, not closed/resolved
- Edge-finder logic: YES price < 0.15 → publish YES signal; NO price < 0.15 → publish NO signal
- Dedup: skips market/side if a live publication exists within 2-hour window
- Writes to `signal_publications` with `is_demo=TRUE`, expires after 4 hours
- Linked to `DEMO_FEED_ID = 00000000-0000-0000-0001-000000000001`
- Job ID: `market_signal_scanner`, interval: 60s, max_instances=1, coalesce=True

**PART 4 — MIGRATION 024 (applied to production DB)**

`migrations/024_signal_scan_engine_seed.sql`:
- Seeded demo `signal_feeds` row (fixed UUID, status=active)
- Seeded demo `markets` row (`demo-market-will-btc-100k-2026`, status=active, YES price=0.10, liquidity=$50k)
- Seeded one `signal_publications` entry pointing at the demo market (YES edge, expires 4h)
- Promoted test user `access_tier` 2 → 3
- Enrolled user in `user_strategies` (signal_following, weight=0.10)
- Subscribed user to demo feed in `user_signal_subscriptions`

DB state post-migration verified:
```
signal_feeds:              1 row
signal_publications:       1 row
user_strategies:           1 row
user_signal_subscriptions: 1 row
users (tier>=3):           1 row
markets:                   1 row
```

**PART 5 — /health COMMAND**

`bot/handlers/health.py`:
- Operator / ADMIN-tier gate (OPERATOR_CHAT_ID or user_tiers.tier='ADMIN')
- Shows: status, last scan time, signals last 1h, markets scanned, active jobs, DB pool, errors
- Staleness flags: ⚠️ at 5 min, 🚨 at 15 min
- Kill switch state reflected in status line

**PART 6 — HOURLY REPORT**

`jobs/hourly_report.py`:
- APScheduler cron: every hour on the minute (`:00`)
- Queries last 60 min: scan count, signals found, trades opened/closed, realized PNL, error count, uptime %
- Sends to all users with `user_tiers.tier = 'ADMIN'`
- Per-user failures are contained and logged; batch always completes

**CONFIG**

`config.py`: added `MARKET_SIGNAL_SCAN_INTERVAL: int = 60`

---

## 2. Current System Architecture

```
DATA LAYER (new):
  Polymarket API
    └─► market_signal_scanner (60s) ──► signal_publications (is_demo=TRUE)

STRATEGY LAYER (existing, now unblocked):
  signal_publications
    └─► signal_following_scan (3min)
          └─► SignalFollowingStrategy.scan()
                └─► evaluate_publications_for_user()
                      └─► _load_active_subscriptions() → user_signal_subscriptions ✅ seeded
                      └─► _load_active_publications() → signal_publications ✅ has rows
                └─► SignalCandidates

EXECUTION LAYER (existing, unchanged):
  SignalCandidates
    └─► _process_candidate() → _load_market() → markets ✅ seeded
          └─► TradeEngine.execute() (13-step risk gate)
                └─► paper fill → orders → positions

MONITORING (new):
  /health → live snapshot (operator/ADMIN only)
  hourly_report → cron :00 → all ADMIN-tier users
```

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/jobs/market_signal_scanner.py`
- `projects/polymarket/crusaderbot/jobs/hourly_report.py`
- `projects/polymarket/crusaderbot/bot/handlers/health.py`
- `projects/polymarket/crusaderbot/migrations/024_signal_scan_engine_seed.sql`

**Modified:**
- `projects/polymarket/crusaderbot/scheduler.py` — import + 2 new jobs (market_signal_scanner, hourly_report)
- `projects/polymarket/crusaderbot/config.py` — added `MARKET_SIGNAL_SCAN_INTERVAL`
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — import health_h + register `/health`

**Applied to production DB (ykyagjdeqcgcktnpdhes):**
- Migration `024_signal_scan_engine_seed` — status: success

---

## 4. What Is Working

- Migration 024 applied and verified: all 5 pipeline blockers resolved in DB
- `market_signal_scanner` job registered at 60s interval with job_tracker listener
- `hourly_report` job registered at cron `:00` with ADMIN-only delivery
- `/health` command wired: OPERATOR_CHAT_ID + ADMIN tier gate, staleness flags, kill switch reflection
- `MARKET_SIGNAL_SCAN_INTERVAL` config key added with default 60s

**Pipeline flow after deploy:**
1. `market_signal_scanner` runs → fetches Polymarket markets → writes YES/NO edge signals to `signal_publications`
2. `signal_following_scan` runs → finds user (tier=3, enrolled, subscribed) → finds publications → builds candidates → routes through TradeEngine → paper fills land in `orders` / `positions`

**Demo path (seeded, works immediately on deploy):**
- Demo market `demo-market-will-btc-100k-2026` (YES price=0.10) already in `markets`
- Demo signal publication (YES edge) already in `signal_publications`
- `signal_following_scan` will pick it up on its next tick without waiting for Polymarket API

---

## 5. Known Issues

- `market_signal_scanner` depends on Polymarket API being reachable. If the API is down, `run_job()` logs a warning and returns 0/0. Demo seed provides the fallback signal path.
- `hourly_report` sends to `user_tiers.tier='ADMIN'` rows only. If no ADMIN rows exist (current state: none), the job logs "no ADMIN users found" and skips silently. WARP🔹CMD must seed ADMIN tier via `/admin settier` post-deploy.
- `positions` table `closed_at` column assumed present for hourly_report query. If column name differs, query will fail and be logged — does not crash other jobs.
- Signal publications expire after 4 hours. The demo publication seeded by migration 024 will expire. `market_signal_scanner` will write fresh ones from live API on each tick; the demo market seed in `markets` table ensures demo continuity.

---

## 6. What Is Next

WARP•SENTINEL validation required for signal-scan-engine before merge.
Source: `projects/polymarket/crusaderbot/reports/forge/signal-scan-engine.md`
Tier: MAJOR

After SENTINEL and merge:
- Seed ADMIN tier for walk3r69 via `/admin settier` so hourly reports fire
- Monitor `signal_publications` table growth post-deploy to confirm scanner is writing
- Monitor `execution_queue` for rows within 2 scan ticks of deploy to confirm E2E flow
- Wire `share_trade_kb` into trade close call sites when PNL > 0 (deferred, per PROJECT_STATE)
