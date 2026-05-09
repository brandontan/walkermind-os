Last Updated : 2026-05-10 02:30 Asia/Jakarta
Status       : Phase 4E CLOB Resilience SENTINEL APPROVED 94/100 (zero critical issues) on branch WARP/CRUSADERBOT-PHASE4E-RESILIENCE (PR #919, audited HEAD d9e67e46) awaiting WARP🔹CMD merge decision. Concurrently: WARP/CRUSADERBOT-ASYNCPG-PGBOUNCER-FIX MINOR lane in flight — adds statement_cache_size=0 to asyncpg.create_pool to stop the post-Phase-4 production /health flap (Sentry DAWN-SNOWFLAKE-1729-G/J/P/Q: 681+14+10+1 events of asyncpg prepared-statement-name collisions under PgBouncer transaction-pooling) and surfaces the asyncpg exception class through database.last_ping_error() into the operator Telegram alert text so any residual flap is diagnosable without a Sentry trip. 817/817 tests green (was 812; +5 new test_database.py covering pool kwarg + ping diagnostic + end-to-end health reason string). Activation posture preserved: USE_REAL_CLOB default False, ENABLE_LIVE_TRADING / EXECUTION_PATH_VALIDATED / CAPITAL_MODE_CONFIRMED neither mutated nor read.

[COMPLETED]
- R12e -- Auto-Redeem System -- PR #869 MERGED 7f8af0b90993 (MAJOR, SENTINEL CONDITIONAL 64/100 -- conditions resolved PR #879)
- R12f -- Operator Dashboard + Kill Switch + Job Monitor -- PR #874 MERGED 2026-05-05 (STANDARD)
- P3a -- Strategy Registry Foundation (BaseStrategy ABC + StrategyRegistry + migration 008) -- PR #876 MERGED 2026-05-05 (STANDARD, FOUNDATION)
- P3b -- Copy Trade strategy (CopyTradeStrategy + scaler + wallet_watcher + migration 009 + /copytrade Telegram + registry bootstrap) -- PR #877 MERGED 2026-05-06 a369129d (MAJOR, SENTINEL CONDITIONAL 71/100 resolved)
- P3c -- Signal Following strategy -- PR #892 MERGED (5ee8487e), MAJOR, SENTINEL APPROVED 100/100
- P3d -- Per-user signal scan loop + execution queue wiring -- PR #897 MERGED (bb08092), MAJOR, SENTINEL APPROVED 94/100. 464/464 tests green.
- R12 Lane 1B -- Sentry SDK wiring, /health demo-readiness, /kill /resume aliases, 3 runbooks -- PR #901 MERGED (MAJOR, NARROW INTEGRATION, SENTINEL APPROVED 95/100, WARP/CRUSADERBOT-R12-PROD-PAPER-DEPLOY)
- Lane 1C -- Demo Data Seeding (CRU-5) -- PR #908 MERGED 2026-05-08 ca5f6f57 (STANDARD, NARROW INTEGRATION, SENTINEL APPROVED 98/100). Migration 014, seed/cleanup scripts, runbook, 514/514 tests green at merge.
- Phase 4A CLOB Adapter -- PR #911 MERGED (MAJOR, SENTINEL APPROVED 89/100, WARP/CRUSADERBOT-PHASE4A-CLOB-ADAPTER). CLOB adapter/auth/market data/mock/factory landed with USE_REAL_CLOB default False and activation guards NOT SET.
- Phase 4B Execution Rewire -- PR #912 MERGED 2026-05-09 cb920661 (MAJOR, NARROW INTEGRATION, SENTINEL PPPROVED 92/100, WARP/CRUSADERBOT-PHASE4B-EXECUTION-REWIRE). domain/execution/live.py moved onto get_clob_client() / ClobClientProtocol with dry-run and guard routing preserved.
- Phase 4C Order Lifecycle -- PR #913 MERGED 2026-05-09 f326879d (MAJOR, NARROW INTEGRATION, SENTINEL APPROVED 96/100 FINAL at HEAD a484012, WARP/CRUSADERBOT-PHASE4C-ORDER-LIFECYCLE). Live polling, fills table, scheduler job, and paper-mode touch+stale path landed.
- Phase 4D WebSocket Order Fills -- PR #915 MERGED 2026-05-09 675e74df0c8dd6ef0e036d408c2d9d9909903c6f (MAJOR, NARROW INTEGRATION, SENTINEL APPROVED 98/100 FINAL at audited HEAD 8197373, merge head 5e287e7, WARP/CRUSADERBOT-PHASE4D-WEBSOCKET-FILLS). WS client/handler/lifecycle/scheduler/main/config wiring landed, 47 new hermetic WS tests + 5 GATE regressions, 111 WS-specific tests + 726/726 hermetic suite green, ruff clean.
- Sentinel gate trail for Phase 4D -- Issue #916 closed completed after verdict/report/state-only trail; no open issues remain.
- R12 final Fly.io production paper deploy -- Issue #900 is closed completed in GitHub; old pending Issue #900 wording is superseded by live issue state.

[IN PROGRESS]
- Phase 4E CLOB Resilience -- WARP/CRUSADERBOT-PHASE4E-RESILIENCE SENTINEL APPROVED 94/100 with zero critical issues (audited HEAD d9e67e46; tracking issue #920). FORGE deliverables verified: CircuitBreaker / RateLimiter / typed exception hierarchy / mainnet_preflight.py (defense-in-depth no-httpx-call test passes) / ops dashboard CLOB circuit card / Telegram on_open alert. Dead code removal confirmed at FORGE tree (services/deposit_watcher.py + services/ledger.py absent, no residual imports). 48/48 new + 45/45 existing CLOB tests green in SENTINEL hermetic env; ruff + py_compile clean on every audited file. Sentinel report: projects/polymarket/crusaderbot/reports/sentinel/resilience.md. PR #919 still open awaiting WARP🔹CMD merge decision.
- WARP/CRUSADERBOT-ASYNCPG-PGBOUNCER-FIX -- MINOR / NARROW INTEGRATION FORGE. database.py init_pool gains statement_cache_size=0 so asyncpg's server-side prepared statement cache is disabled for PgBouncer transaction-pooling compatibility (resolves Sentry DAWN-SNOWFLAKE-1729-G/J/P/Q/K/M/N/H/R/F/E). database.ping() captures exception class into module-level _last_ping_error and exposes it via last_ping_error(); logger.error gains exc_info=True so Sentry receives the structured exception. monitoring/health.py:_with_timeout accepts optional reason_provider so checks["database"] now reads "error: database reported unhealthy (<AsyncpgClass>)" — operators stop guessing without a Sentry trip. New tests/test_database.py: 5 hermetic tests asserting (a) create_pool kwarg, (b) ping success clears last error, (c) failure records class name, (d) exc_info=True is set, (e) end-to-end class name lands in run_health_checks output. 817/817 tests green; ruff clean on touched files. Activation posture preserved (no guard mutation, no trading path touched). Forge report: projects/polymarket/crusaderbot/reports/forge/asyncpg-pgbouncer-fix.md. SENTINEL NOT REQUIRED per task tier. Awaiting WARP🔹CMD review + merge decision.

[NOT STARTED]
- R13a Leaderboard -- paper P&l ranking, /leaderboard command, top 10, daily scheduler update.
- R13b Backtesting Engine -- replay historical Polymarket data and output win rate, Sharpe ratio, max drawdown, EV.
- R13c Multi-Signal Fusion -- add sentiment + on-chain volume to copy-trade signal with weighted combiner; MAJOR tier.
- R13d Web Dashboard (Admin) -- React + FastAPI admin views for users, positions, P&l chart, scheduler status.
- R13e Referral System -- referral code, referee discount, and referral accounting.
- R13f Strategy Marketplace -- tier 4 named strategies, subscription model, 10% platform take.

[NEXT PRIORITY]
- WARP🔹CMD review + merge decision on WARP/CRUSADERBOT-ASYNCPG-PGBOUNCER-FIX (MINOR). Source: projects/polymarket/crusaderbot/reports/forge/asyncpg-pgbouncer-fix.md. Resolves recurring production /health DB flap; expected to silence Sentry DAWN-SNOWFLAKE-1729-G/J/P/Q on next deploy.
- WARP🔹CMD merge decision on PR #919 Phase 4E CLOB Resilience (SENTINEL APPROVED 94/100, zero critical issues). Source report: projects/polymarket/crusaderbot/reports/sentinel/resilience.md.
- Keep activation guards NOT SET. No live trading activation, no USE_REAL_CLOB owner flip, no capital mode change.
- Post-Phase-4E candidates (NOT in scope for this lane): R13a Leaderboard (growth backlog), WARP/CRUSADERBOT-MAINNET-ONCHAIN-PREFLIGHT (on-chain wallet/approval/balance checks complementing the local preflight script), WARP/CRUSADERBOT-OPS-CIRCUIT-RESET (operator endpoint to force_close the breaker via /ops + Telegram).
- Post-merge follow-up candidate: WARP/CRUSADERBOT-DB-POOL-HARDENING (STANDARD) — only if /health flaps persist after asyncpg-pgbouncer-fix lands; would tune max_inactive_connection_lifetime / connect_timeout and revisit DB_POOL_MAX=5.

[KNOWN ISSUES]
- /deposit has no tier gate (intentional, non-blocking)
- services/* dead code -- CLEARED in Phase 4E (deposit_watcher.py and ledger.py removed; remaining services/* files are live consumers).
- check_alchemy_ws is TCP-only (no full WS handshake) -- follow-up
- lib/ F401 leakage -- CLEARED in Phase 4E (5 occurrences fixed; ruff check lib/ is clean).
- ENABLE_LIVE_TRADING code default in config.py is True (legacy); fly.toml [env] overrides to "false" so prod posture is correct. Code default alignment is deferred to WARP/config-guard-default-alignment.
- integrations/polymarket.py _build_clob_client() is dead code in live execution path after Phase 4B; still indirectly referenced by submit_live_redemption(). Cleanup deferred to WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP (MINOR, post-Phase-4B merge).
- Activation guards remain NOT SET and must not be changed without owner decision.
- R13 backlog is post-MVP growth work; none of it is required to keep current paper-safe runtime functional.
- [DEFERRED] Concurrent HALF_OPEN trial race in CircuitBreaker._record_failure (circuit_breaker.py:175-208) may multiply on_open invocations and restart cool-down — found in PR #919 Phase 4E SENTINEL audit. P2, no safety implication. Mitigation: gate the else-branch trip on prior_state==CLOSED.
- [DEFERRED] CLOB circuit-open Telegram alert text uses plain markdown rather than MarkdownV2 (integrations/clob/__init__.py:161-166) — found in PR #919 Phase 4E. P2, acceptable for the static template; flagged in FORGE Known Issues already.
- [DEFERRED] Ops dashboard CLOB circuit card refreshes only via the page-level 30s meta refresh (api/ops.py:370-372) — found in PR #919 Phase 4E. P2, SSE/WS push is a future enhancement.
- [DEFERRED] Package-level (single-instance) CircuitBreaker — adequate for single-broker steady state; per-broker instances can be passed via the circuit_breaker= kwarg if needed. Found in PR #919 Phase 4E. P2, flagged in FORGE Known Issues already.
- One open PR as of 2026-05-10 01:35 Asia/Jakarta: PR #919 Phase 4E CLOB Resilience on branch WARP/CRUSADERBOT-PHASE4E-RESILIENCE awaiting WARP🔹CMD merge decision (SENTINEL APPROVED 94/100).
- One open GitHub issue as of 2026-05-10 01:35 Asia/Jakarta: tracking issue #920 awaiting WARP🔹CMD merge decision. Tracking issue #918 was closed not_planned by WARP🔹CMD housekeeping after PR #919 was opened; the work is delivered and tracked via PR #919, which Refs / Supersedes #918.

<!-- CD verify: 2026-05-09 16:00 -->
