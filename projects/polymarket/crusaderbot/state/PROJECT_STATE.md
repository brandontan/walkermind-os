Last Updated : 2026-05-10 00:25 Asia/Jakarta
Status       : Phase 4E CLOB Resilience FORGE complete on branch WARP/CRUSADERBOT-PHASE4E-RESILIENCE — typed error classification (ClobAuthError / ClobRateLimitError / ClobServerError / ClobTimeoutError / ClobNetworkError / ClobMaxRetriesError / ClobCircuitOpenError), CircuitBreaker (CLOSED→OPEN→HALF_OPEN with threshold=5 / reset=60s / Telegram on_open page), token-bucket RateLimiter (10 RPS default), mainnet_preflight.py (5 local checks, no broker call), and ops dashboard "CLOB circuit" card landed. Wraps post_order / cancel_order / get_order. Dead code removed: services/deposit_watcher.py (legacy Alchemy WS, replaced by scheduler.watch_deposits) and services/ledger.py (legacy sub-account ledger, replaced by wallet/ledger.py); 5 lib/ F401 leakages cleared (logic_arb.py:42, value_investor.py:30, weather_arb.py:25,29, strategy_base.py:34). 812/812 crusaderbot tests green (100/100 existing CLOB-related + 48 new resilience tests). Ruff clean on every touched file. Phases 4A/4B/4C/4D remain merged on main; this PR adds production-grade resilience around the existing REST surface without touching any activation guard. PR #919 open; tracking issue #918 closed not_planned by WARP🔹CMD housekeeping (the lane is now superseded by PR #919). SENTINEL REQUIRED before merge. Activation posture stays paper-safe: USE_REAL_CLOB default False, ENABLE_LIVE_TRADING not mutated, EXECUTION_PATH_VALIDATED / CAPITAL_MODE_CONFIRMED untouched, no live trading activation in this PR.

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
- Phase 4E CLOB Resilience -- WARP/CRUSADERBOT-PHASE4E-RESILIENCE FORGE complete (Tier MAJOR, Claim FULL RUNTIME INTEGRATION, SENTINEL REQUIRED). PR #919 supersedes closed tracking issue #918 (Refs #918; #918 closed not_planned by WARP🔹CMD housekeeping, label warp:forge). CircuitBreaker / RateLimiter / typed exception hierarchy / mainnet_preflight.py / ops dashboard CLOB circuit card / Telegram on_open alert all landed, dead code removed, lib F401 cleared, 812/812 tests green, ruff clean. PR open against main awaiting WARP•SENTINEL audit before merge.

[NOT STARTED]
- R13a Leaderboard -- paper P&l ranking, /leaderboard command, top 10, daily scheduler update.
- R13b Backtesting Engine -- replay historical Polymarket data and output win rate, Sharpe ratio, max drawdown, EV.
- R13c Multi-Signal Fusion -- add sentiment + on-chain volume to copy-trade signal with weighted combiner; MAJOR tier.
- R13d Web Dashboard (Admin) -- React + FastAPI admin views for users, positions, P&l chart, scheduler status.
- R13e Referral System -- referral code, referee discount, and referral accounting.
- R13f Strategy Marketplace -- tier 4 named strategies, subscription model, 10% platform take.

[NEXT PRIORITY]
- WARP•SENTINEL validation required for Phase 4E CLOB Resilience before merge. Source: projects/polymarket/crusaderbot/reports/forge/resilience.md. Tier: MAJOR. Claim: FULL RUNTIME INTEGRATION.
- After SENTINEL approval: WARP🔹CMD merge decision on the Phase 4E PR.
- Keep activation guards NOT SET. No live trading activation, no USE_REAL_CLOB owner flip, no capital mode change.
- Post-Phase-4E candidates (NOT in scope for this lane): R13a Leaderboard (growth backlog), WARP/CRUSADERBOT-MAINNET-ONCHAIN-PREFLIGHT (on-chain wallet/approval/balance checks complementing the local preflight script), WARP/CRUSADERBOT-OPS-CIRCUIT-RESET (operator endpoint to force_close the breaker via /ops + Telegram).

[KNOWN ISSUES]
- /deposit has no tier gate (intentional, non-blocking)
- services/* dead code -- CLEARED in Phase 4E (deposit_watcher.py and ledger.py removed; remaining services/* files are live consumers).
- check_alchemy_ws is TCP-only (no full WS handshake) -- follow-up
- lib/ F401 leakage -- CLEARED in Phase 4E (5 occurrences fixed; ruff check lib/ is clean).
- ENABLE_LIVE_TRADING code default in config.py is True (legacy); fly.toml [env] overrides to "false" so prod posture is correct. Code default alignment is deferred to WARP/config-guard-default-alignment.
- integrations/polymarket.py _build_clob_client() is dead code in live execution path after Phase 4B; still indirectly referenced by submit_live_redemption(). Cleanup deferred to WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP (MINOR, post-Phase-4B merge).
- Activation guards remain NOT SET and must not be changed without owner decision.
- R13 backlog is post-MVP growth work; none of it is required to keep current paper-safe runtime functional.
- One open PR as of 2026-05-10 00:25 Asia/Jakarta: PR #919 Phase 4E CLOB Resilience on branch WARP/CRUSADERBOT-PHASE4E-RESILIENCE awaiting SENTINEL.
- No open GitHub issues as of 2026-05-10 00:25 Asia/Jakarta. Tracking issue #918 was closed not_planned by WARP🔹CMD housekeeping after PR #919 was opened; the work is delivered and tracked via PR #919, which Refs / Supersedes #918 rather than auto-closing it.

<!-- CD verify: 2026-05-09 16:00 -->
