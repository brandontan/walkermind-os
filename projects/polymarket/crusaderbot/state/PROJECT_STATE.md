Last Updated : 2026-05-10 18:00 Asia/Jakarta
Status       : Phase 5A–5D + asyncpg fix all merged (PRs #923–#928). Phase 5J emergency menu redesign PR #932 open, STANDARD, WARP•SENTINEL APPROVED 90/100, 0 criticals, pending WARP🔹CMD merge decision. Runtime posture unchanged: PAPER ONLY, no activation guards flipped, no execution path touched.

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
- asyncpg + Supabase Supavisor fix -- PR #923 merged, MINOR, branch WARP/CRUSADERBOT-ASYNCPG-SUPABASE-FIX. Resolves Sentry DAWN-SNOWFLAKE-1729-G/J/P/Q. 822/822 tests green.
- Phase 5A global-handlers -- PR #924 merged, MINOR, declared WARP/CRUSADERBOT-PHASE5A-GLOBAL-HANDLERS. _text_router priority fix, 5-button main menu, /settings command, my_trades view. 784/784 tests green.
- Phase 5C strategy preset system -- PR #925 merged, MAJOR, branch WARP/CRUSADERBOT-PHASE5C-PRESETS, SENTINEL APPROVED 92/100. 3 presets (signal_sniper / value_hunter / full_auto), DB migration 016, paper-only activation enforced. 814/814 tests green.
- Phase 5B dashboard hierarchy redesign -- PR #926 merged, STANDARD, declared WARP/CRUSADERBOT-PHASE5B-DASHBOARD, SENTINEL APPROVED 97/100. Single-message hierarchy, four sections, /start routing for existing Tier 2+ users.
- SENTINEL report Phase 5B + 5C -- PR #927 merged. Report: projects/polymarket/crusaderbot/reports/sentinel/phase5bc-preset-dashboard.md.
- Phase 5D 2-column grid + Copy/Auto Trade menu split -- PR #928 merged, STANDARD. grid_rows() helper, main menu 5→6 buttons, 🐋 Copy Trade entry point, preset trim 5→3. 57/57 Phase 5D + preset tests green.

[IN PROGRESS]
- Phase 5J emergency menu redesign -- PR #932 open, STANDARD, WARP•SENTINEL APPROVED 90/100 (0 criticals), pending WARP🔹CMD merge decision. branch WARP/CRUSADERBOT-PHASE5J-EMERGENCY. Lock Account DB-enforced (migration 017), /unlock operator command, 13 hermetic tests, CI green. Report: projects/polymarket/crusaderbot/reports/sentinel/phase5j-emergency.md.

[NOT STARTED]
- Phase 5E -- Copy Trade dashboard + wallet discovery. Next active lane, unblocked by Phase 5D merge (PR #928).
- WARP/CRUSADERBOT-MAINNET-ONCHAIN-PREFLIGHT -- on-chain wallet, allowance, balance, and signer readiness checks complementing scripts/mainnet_preflight.py; no live trading activation and no real orders.
- WARP/CRUSADERBOT-OPS-CIRCUIT-RESET -- operator endpoint / Telegram command to force_close the CLOB circuit breaker after incident review; no broker calls and no guard flips.
- R13a Leaderboard -- paper P&L ranking, /leaderboard command, top 10, daily scheduler update.
- R13b Backtesting Engine -- replay historical Polymarket data and output win rate, Sharpe ratio, max drawdown, and EV.
- R13c Multi-Signal Fusion -- combine sentiment and on-chain volume into copy-trade signal weighting; MAJOR if strategy execution behavior changes.
- R13d Web Dashboard (Admin) -- React + FastAPI admin views for users, positions, P&L chart, and scheduler status.
- R13e Referral System -- referral code, referee discount, and referral accounting.
- R13f Strategy Marketplace -- tier 4 named strategies, subscription model, and 10% platform take.

[NEXT PRIORITY]
- WARP🔹CMD merge decision — PR #932 Phase 5J emergency menu redesign (STANDARD, SENTINEL APPROVED 90/100, 0 criticals). Report: projects/polymarket/crusaderbot/reports/sentinel/phase5j-emergency.md.
- After merge: dispatch Phase 5E (Copy Trade dashboard + wallet discovery) as next active lane.
- Keep activation guards NOT SET. No live trading activation, no capital mode change, no real order, no owner guard flip.

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
