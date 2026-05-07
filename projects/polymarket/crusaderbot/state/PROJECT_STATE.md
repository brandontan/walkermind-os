Last Updated : 2026-05-08 14:00 Asia/Jakarta
Status       : R12 final Fly.io deployment Lane 1B PR OPEN on WARP/CRUSADERBOT-R12-PROD-PAPER-DEPLOY (MAJOR, NARROW INTEGRATION — downgraded from issue-stated FULL RUNTIME because operator-executed prod verification cannot be run from the WARP•FORGE sandbox). Sentry SDK wiring (DSN-gated no-op when unset), POST /admin/sentry-test verification endpoint, /health demo-readiness contract (status / uptime_seconds / version / mode / timestamp + R12b deep-deps), fly.toml primary_region sin → iad, /kill and /resume Telegram aliases, 3 runbooks (alerts.md, kill-switch-procedure.md, rollback-procedure.md). 473/473 tests green (was 464). Pre-flight cleanup PR #899 still awaiting CMD review (separate lane). CHECKPOINT 1 — HARD PAUSE: awaiting WARP🔹CMD review + WARP•SENTINEL audit + operator-executed prod verification per runbooks before Lane 1C dispatch.

[COMPLETED]
- PR #852 — feat(crusaderbot): import full Replit build R1-R11
- PR #853 — sentinel: crusaderbot-replit-import PASS (post-fix)
- C1 resolved: KELLY_FRACTION applied, capital_alloc_pct capped <1.0
- C2 resolved: migrations/004 idempotent DO $$ blocks
- C3 resolved: Tier 3 promotion gated on MIN_DEPOSIT_USDC
- R12b — Fly.io health probes + operator alerts + JSON logging (PR #856 merged)
- PR #857 — chore: state sync post-PR #856
- PR #858 — chore: state sync post-PR #857
- PR #860 — chore: ROADMAP R12b drift fix + WORKTODO init (STANDARD, merged)
- R12a — CI/CD Pipeline GitHub Actions + Fly.io — PR #855 MERGED 2026-05-04 (STANDARD)
- R12c — Auto-Close / Take-Profit exit watcher — PR #865 MERGED 2026-05-05 (MAJOR, SENTINEL APPROVED 95/100)
- R12d — Telegram Position UX (live monitor + force close) — PR #868 MERGED 4f5e12201964 (STANDARD)
- R12e — Auto-Redeem System — PR #869 MERGED 7f8af0b90993 (MAJOR, SENTINEL CONDITIONAL 64/100 — conditions resolved PR #879)
- R12f — Operator Dashboard + Kill Switch + Job Monitor — PR #874 MERGED 2026-05-05 (STANDARD)
- P3a — Strategy Registry Foundation (BaseStrategy ABC + StrategyRegistry + migration 008) — PR #876 MERGED 2026-05-05 (STANDARD, FOUNDATION)
- P3b — Copy Trade strategy (CopyTradeStrategy + scaler + wallet_watcher + migration 009 + /copytrade Telegram + registry bootstrap) — PR #877 MERGED 2026-05-06 a369129d (MAJOR, SENTINEL CONDITIONAL 71/100 resolved)
- R12 Live Readiness batch — Live Opt-In Checklist + Live→Paper Auto-Fallback + Daily P&L Summary — PR #883 MERGED 5a9cb22a (STANDARD, NARROW INTEGRATION)
- Cleanup legacy polyquantbot directory — PR #891 MERGED (MINOR, Issue #890 closed)
- P3c — Signal Following strategy — PR #892 MERGED (5ee8487e), MAJOR, SENTINEL APPROVED 100/100
- P3d — Per-user signal scan loop + execution queue wiring — PR #897 MERGED (bb08092), MAJOR, SENTINEL APPROVED 94/100. Crash-recovery resume path, subscribe/unsubscribe enrollment, dual-layer dedup, migration 011+012. 464/464 tests green.

[IN PROGRESS]
- Pre-flight cleanup lane on WARP/CRUSADERBOT-PREFLIGHT-CLEANUP (STANDARD, NARROW INTEGRATION — reclassified from MINOR per Codex P2 finding; CMD-ratified): 15 F401 cleared across 7 files, MIN-01 user_id annotations on 3 copy_trade handler helpers, MIN-02 dispatcher phase comment, MIN-03 migration 013 (copy_trade_events.copy_target_id FK referential action ON DELETE CASCADE → ON DELETE SET NULL — audit rows survive parent delete), ROADMAP R12d/R12e/R12f naming aligned to actual executed lanes. PR #899.
- R12 final Fly.io deployment Lane 1B on WARP/CRUSADERBOT-R12-PROD-PAPER-DEPLOY (MAJOR, NARROW INTEGRATION — issue #900). Sentry SDK + /admin/sentry-test + /health demo-readiness + fly.toml sin→iad + /kill /resume aliases + 3 runbooks. PR open. CHECKPOINT 1 — HARD PAUSE awaiting CMD review, SENTINEL audit, operator-executed prod verification per runbooks. 473/473 tests green.

[NOT STARTED]
- R12 final Fly.io deployment Lane 1C — demo data seeding (MINOR, idempotent, gated on Lane 1B merge per batch checkpoint protocol)
- R12 final Fly.io deployment Lane 2C — Telegram demo polish (MINOR, gated on Lane 1C merge)

[NEXT PRIORITY]
- WARP🔹CMD review + WARP•SENTINEL audit on R12 Lane 1B PR. Then operator executes the prod verification checklist per the three new runbooks (Sentry test event, Fly.io alert simulation, /kill ack < 3s, /resume, rollback dry-run) and confirms timings. Activation guards (EXECUTION_PATH_VALIDATED, CAPITAL_MODE_CONFIRMED, ENABLE_LIVE_TRADING) remain NOT SET throughout.

[KNOWN ISSUES]
- /deposit no tier gate (intentional, non-blocking)
- services/* dead code (LOW, post-R12 cleanup)
- check_alchemy_ws is TCP-only (no full WS handshake) — follow-up
- lib/ F401 leakage (LOW, 5 occurrences across lib/strategies/logic_arb.py, lib/strategies/value_investor.py, lib/strategies/weather_arb.py, lib/strategy_base.py) — pre-existing repo-root ruff failure surfaced by Codex on PR #899; deferred to WARP/LIB-F401-CLEANUP (post-demo MINOR) per WARP🔹CMD scope-boundary hold; cross-project impact requires audit before cleanup
- ENABLE_LIVE_TRADING code default in config.py:88 is True (legacy); fly.toml [env] block overrides to "false" so prod posture is correct. Code default disagrees with intent of "all guards default OFF" — flag for SENTINEL, deferred to a post-demo MINOR alignment lane.
- R12 Lane 1B prod verification artefacts (7 deferred Done-Criteria items: /health 200 in prod, Sentry test event in prod project, Fly.io alert simulation timings, /kill ack timing, /resume timing, /ops_dashboard screenshot, rollback dry-run outcome) are runbook-documented but operator-executed; explicitly NOT CLAIMED CLOSED by PR #901. See reports/forge/r12-prod-paper-deploy.md §5b for the full deferred-criteria table. Issue #900 stays open until operator attaches the seven artefacts.

<!-- CD verify: 2026-05-08 00:30 -->
