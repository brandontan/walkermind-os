Last Updated : 2026-05-10 03:30 Asia/Jakarta
Status       : Phase 4E CLOB Resilience is merged on main via PR #919 (merge commit f18e25cb5cb516f6d41e0e87fff1c0915d489f45) after WARP•SENTINEL APPROVED 94/100 with zero critical issues. Phase 4 CLOB integration is now 5/5 merged: adapter/auth, execution rewire, order lifecycle, websocket fills, and resilience/mainnet local preflight. Current runtime posture remains PAPER ONLY: USE_REAL_CLOB default False, ENABLE_LIVE_TRADING not enabled, EXECUTION_PATH_VALIDATED not set, CAPITAL_MODE_CONFIRMED not set, and no owner activation guard was flipped. Concurrently: WARP/CRUSADERBOT-ASYNCPG-SUPABASE-FIX MINOR lane in flight to silence the post-Phase-4 production /health flap (Sentry DAWN-SNOWFLAKE-1729-G/J/P/Q: 681+14+10+1 events of asyncpg prepared-statement-cache collisions under Supabase Supavisor transaction-pool multiplexing) — adds statement_cache_size=0 + server_settings.application_name=crusaderbot to asyncpg.create_pool, a Supavisor pooler-awareness startup warning, and surfaces the asyncpg exception class via database.last_ping_error() into the operator Telegram alert string. 822/822 tests green (was 812; +10 new test_database.py covering pool kwargs + diagnostic warning host/port branches + ping diagnostic + end-to-end health reason string). Activation posture preserved (no guard mutation, no trading path touched). Supersedes WARP/CRUSADERBOT-ASYNCPG-PGBOUNCER-FIX (PR #922).

[COMPLETED]
- Phase 4A CLOB Adapter -- PR #911 merged, MAJOR, SENTINEL APPROVED 89/100, branch WARP/CRUSADERBOT-PHASE4A-CLOB-ADAPTER.
- Phase 4B Execution Rewire -- PR #912 merged, MAJOR, SENTINEL APPROVED 92/100, branch WARP/CRUSADERBOT-PHASE4B-EXECUTION-REWIRE.
- Phase 4C Order Lifecycle -- PR #913 merged, MAJOR, SENTINEL APPROVED 96/100, branch WARP/CRUSADERBOT-PHASE4C-ORDER-LIFECYCLE.
- Phase 4D WebSocket Order Fills -- PR #915 merged, MAJOR, SENTINEL APPROVED 98/100, branch WARP/CRUSADERBOT-PHASE4D-WEBSOCKET-FILLS.
- Phase 4E CLOB Resilience -- PR #919 merged, MAJOR, FULL RUNTIME INTEGRATION, SENTINEL APPROVED 94/100, branch WARP/CRUSADERBOT-PHASE4E-RESILIENCE.
- Sentinel gate trail for Phase 4E -- Issue #920 closed completed after PR #921 merged Sentinel report/state into the Phase 4E source branch and PR #919 merged to main.
- R12 final Fly.io production paper deploy -- Issue #900 is closed completed in GitHub; old pending wording is superseded by current live issue state.
- Phase 3 strategy plane -- P3a/P3b/P3c/P3d merged with required Sentinel coverage; strategy registry, copy trade, signal following, and per-user signal scan queue are live in paper-safe posture.
- Demo data seeding -- PR #908 merged, STANDARD, SENTINEL APPROVED 98/100; migration 014, seed/cleanup scripts, runbook, and tests landed.
- Operator dashboard and kill switch baseline -- PR #874 merged, STANDARD; /ops dashboard and operator controls are available.

[IN PROGRESS]
- WARP/CRUSADERBOT-ASYNCPG-SUPABASE-FIX -- MINOR / NARROW INTEGRATION FORGE. database.py init_pool gains statement_cache_size=0 and server_settings={"application_name": "crusaderbot"} so prepared-statement names survive Supabase Supavisor transaction-pool multiplexing and bot connections are identifiable in pg_stat_activity (resolves Sentry DAWN-SNOWFLAKE-1729-G/J/P/Q/K/M/N/H/R/F/E). New _warn_if_supavisor_transaction_pool helper logs a single WARNING when DATABASE_URL host contains "pooler.supabase" AND port == 6543 — purely informational, never blocks startup. database.ping() captures exception class into module-level _last_ping_error, exposes it via last_ping_error(), and logger.error gains exc_info=True so Sentry receives the structured exception. monitoring/health.py:_with_timeout accepts optional reason_provider so checks["database"] now reads "error: database reported unhealthy (<AsyncpgClass>)". New tests/test_database.py: 10 hermetic tests covering both pool kwargs, the three Supavisor warning host/port branches (transaction-pool warns, session-pool stays quiet, non-Supabase host stays quiet), malformed-DSN noop, ping success/failure semantics, exc_info=True, and end-to-end class-name surfacing through run_health_checks. 822/822 tests green; ruff clean on touched files. Activation posture preserved (no guard mutation, no trading path touched). Forge report: projects/polymarket/crusaderbot/reports/forge/asyncpg-supabase-fix.md. SENTINEL NOT REQUIRED per task tier. Supersedes PR #922 (WARP/CRUSADERBOT-ASYNCPG-PGBOUNCER-FIX) — the new lane subsumes the old one and adds Supavisor-specific contracts. Awaiting WARP🔹CMD review + merge decision.

[NOT STARTED]
- WARP/CRUSADERBOT-MAINNET-ONCHAIN-PREFLIGHT -- on-chain wallet, allowance, balance, and signer readiness checks complementing scripts/mainnet_preflight.py; no live trading activation and no real orders.
- WARP/CRUSADERBOT-OPS-CIRCUIT-RESET -- operator endpoint / Telegram command to force_close the CLOB circuit breaker after incident review; no broker calls and no guard flips.
- R13a Leaderboard -- paper P&L ranking, /leaderboard command, top 10, daily scheduler update.
- R13b Backtesting Engine -- replay historical Polymarket data and output win rate, Sharpe ratio, max drawdown, and EV.
- R13c Multi-Signal Fusion -- combine sentiment and on-chain volume into copy-trade signal weighting; MAJOR if strategy execution behavior changes.
- R13d Web Dashboard (Admin) -- React + FastAPI admin views for users, positions, P&L chart, and scheduler status.
- R13e Referral System -- referral code, referee discount, and referral accounting.
- R13f Strategy Marketplace -- tier 4 named strategies, subscription model, and 10% platform take.

[NEXT PRIORITY]
- WARP🔹CMD review + merge decision on WARP/CRUSADERBOT-ASYNCPG-SUPABASE-FIX (MINOR). Source: projects/polymarket/crusaderbot/reports/forge/asyncpg-supabase-fix.md. Resolves recurring production /health DB flap; expected to silence Sentry DAWN-SNOWFLAKE-1729-G/J/P/Q on next deploy. Close PR #922 (WARP/CRUSADERBOT-ASYNCPG-PGBOUNCER-FIX) as superseded once the new PR is opened.
- Dispatch WARP/CRUSADERBOT-MAINNET-ONCHAIN-PREFLIGHT as the next safety lane before any owner live-trading decision. Recommended tier: MAJOR. Claim: FULL RUNTIME INTEGRATION if it touches real wallet/on-chain readiness; SENTINEL REQUIRED. Scope: read-only wallet/chain/preflight verification only, no order submission, no ENABLE_LIVE_TRADING, no USE_REAL_CLOB default flip.
- Keep activation guards NOT SET. No live trading activation, no capital mode change, no real order, no owner guard flip.
- R13a Leaderboard is queued after the safety lane if product/growth work is prioritized over mainnet readiness.
- Post-merge follow-up candidate: WARP/CRUSADERBOT-DB-POOL-HARDENING (STANDARD) — only if /health flaps persist after asyncpg-supabase-fix lands; would tune max_inactive_connection_lifetime / connect_timeout and revisit DB_POOL_MAX=5.

[KNOWN ISSUES]
- /deposit has no tier gate (intentional, non-blocking).
- check_alchemy_ws is TCP-only and does not perform a full WebSocket handshake; follow-up low priority.
- ENABLE_LIVE_TRADING code default in config.py is True (legacy); fly.toml [env] overrides to "false" so production posture is correct. Code default alignment remains deferred to WARP/config-guard-default-alignment.
- integrations/polymarket.py _build_clob_client() is dead in the live execution path after Phase 4B but still indirectly referenced by submit_live_redemption(); cleanup deferred to WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP.
- Activation guards remain NOT SET and must not be changed without owner decision.
- R13 backlog is post-MVP growth work; none is required to keep current paper-safe runtime functional.
- [DEFERRED] Concurrent HALF_OPEN trial race in CircuitBreaker._record_failure may multiply on_open invocations and restart cool-down; P2, no safety implication.
- [DEFERRED] CLOB circuit-open Telegram alert text uses plain markdown rather than MarkdownV2; P2, acceptable for static template.
- [DEFERRED] Ops dashboard CLOB circuit card refreshes only via page-level 30s meta refresh; SSE/WS push is future enhancement.
- [DEFERRED] Package-level single-instance CircuitBreaker is adequate for single-broker steady state; per-broker instances can be passed via circuit_breaker kwarg if needed.

<!-- CD verify: 2026-05-10 02:59 -->
