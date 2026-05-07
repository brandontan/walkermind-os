# WARP•FORGE Report — P3d Signal Scan + Execution Queue

Branch: WARP/CRUSADERBOT-P3D-SIGNAL-SCAN-EXECUTION-QUEUE
Date: 2026-05-07 20:51 Asia/Jakarta
Tier: MAJOR
Claim Level: FULL RUNTIME INTEGRATION (scoped P3d path only)

---

## 1. What Was Built

Per-user signal_following scan loop + execution queue wiring (P3d).

The P3 strategy plane is now wired into the risk gate / execution queue
path. Subscribed users with signal_following strategy enrolled and auto_trade_on
have their active feed publications scanned per tick, routed through the
13-step risk gate, and on approval inserted into a new execution_queue table
before being submitted to the execution router.

PR #895 scope (signal_following strategy availability key) is incorporated
under this MAJOR lane and superseded. No standalone MINOR PR #895 merge required.

---

## 2. Current System Architecture (P3d slice)

```
APScheduler (signal_following_scan, SIGNAL_SCAN_INTERVAL)
    |
    v
services/signal_scan/signal_scan_job.run_once()
    |
    +-- _load_enrolled_users()
    |       user_strategies (strategy_name='signal_following', enabled=TRUE)
    |       + users (auto_trade_on=TRUE, paused=FALSE, access_tier>=3)
    |       + wallets + user_settings + sub_accounts + user_risk_profile
    |
    +-- StrategyRegistry.instance().get('signal_following')
    |
    +-- SignalFollowingStrategy.scan(MarketFilters, UserContext)
    |       -> signal_evaluator -> signal_publications (pure DB reads)
    |       -> list[SignalCandidate]
    |
    +-- _process_candidate() per candidate:
            |
            +-- execution_queue pre-check (UNIQUE user_id+publication_id)
            |       skip if already queued/executed
            |
            +-- risk_gate.evaluate(GateContext)  [13 steps — MANDATORY]
            |       reject -> log, return
            |
            +-- INSERT execution_queue ON CONFLICT DO NOTHING
            |       conflict -> skip (concurrent tick raced us)
            |
            +-- router_execute()  [paper/live via live guard]
            |
            +-- UPDATE execution_queue (executed / failed)
```

Deduplication:
- Outer: execution_queue UNIQUE (user_id, publication_id) — permanent across ticks
- Inner: idempotency_keys 30-min window (risk gate step 10) — short-circuit for
  recent rejections (avoids repeated gate evaluations every SIGNAL_SCAN_INTERVAL)

---

## 3. Files Created / Modified

Created:
- projects/polymarket/crusaderbot/migrations/011_execution_queue.sql
- projects/polymarket/crusaderbot/services/signal_scan/__init__.py
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py
- projects/polymarket/crusaderbot/tests/test_signal_scan_job.py

Modified:
- projects/polymarket/crusaderbot/domain/risk/constants.py
  — added "signal_following": ["conservative","balanced","aggressive"] to
    STRATEGY_AVAILABILITY (supersedes PR #895; SENTINEL must verify key
    matches SignalFollowingStrategy.name and risk_profile_compatibility)
- projects/polymarket/crusaderbot/scheduler.py
  — added signal_following_scan job (sf_scan_job.run_once, SIGNAL_SCAN_INTERVAL)

---

## 4. What Is Working

- 459/459 tests green (435 pre-existing + 24 new P3d tests)
- signal_following available for all 3 risk profiles in STRATEGY_AVAILABILITY
- STRATEGY_AVAILABILITY key exactly matches SignalFollowingStrategy.name
  and risk_profile_compatibility (test_signal_following_matches_strategy_name)
- Dual-layer deduplication functional:
  execution_queue UNIQUE partial index (user_id, publication_id) + idempotency_keys
- Risk gate mandatory: router_execute NEVER called without risk_evaluate approval
- Activation guards NOT SET and NOT mutated anywhere in new code
- asyncio only — no threading
- Kelly fraction unchanged at 0.25
- No phase*/ folders
- Scan failures per user are isolated (one bad user cannot crash the full tick)
- Structured JSON logging at every outcome: accepted, skipped_dedup,
  skipped_concurrent_dedup, skipped_market_not_synced, rejected, failed

---

## 5. Known Issues

- MarketFilters (categories, blacklisted_market_ids) are hardcoded to permissive
  defaults — per-user filter configuration reserved for a future lane.
  Risk gate liquidity floor covers the critical minimum.
- Old scheduler.run_signal_scan() (copy_trade, old domain/signal/ interface)
  runs alongside the new signal_following_scan. Migration of old scan to the
  P3a/P3b BaseStrategy interface is out of scope for P3d.
- execution_queue does not implement a retry for 'failed' rows — if router_execute
  raises, the publication is permanently marked failed. A future lane may add
  a retry policy for recoverable errors.

---

## 6. What Is Next

WARP•SENTINEL validation required before merge.

Validation Target:
- STRATEGY_AVAILABILITY["signal_following"] key matches strategy name and
  risk_profile_compatibility exactly
- risk gate is mandatory (no execution path bypasses it)
- execution_queue UNIQUE index prevents re-execution
- activation guards remain NOT SET in all new code
- no full Kelly (a=0.25 enforced in gate.py, unchanged)
- 459/459 tests green

Validation Tier: MAJOR
Claim Level: FULL RUNTIME INTEGRATION (scoped P3d path only — signal_following
             scan loop, execution queue, risk gate wiring)
Validation Target: per-user signal_following scan + risk gate + execution queue dedup
Not in Scope: old copy_trade scan loop migration, per-user MarketFilters config,
             execution_queue retry policy, R12 final deployment
Suggested Next: WARP•SENTINEL audit before merge, then R12 final Fly.io deployment
