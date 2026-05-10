Last Updated : 2026-05-10 10:00 Asia/Jakarta
Status       : WARP•SENTINEL MAJOR audit complete for Phase 5C preset system (PR #925, APPROVED 92/100) and STANDARD focused audit complete for Phase 5B dashboard (PR #926, APPROVED 97/100). Both PRs clear for WARP🔹CMD merge decision. Four lanes await merge: 5C presets (MAJOR, SENTINEL APPROVED), 5B dashboard (STANDARD, SENTINEL APPROVED), 5A global-handlers (MINOR), ASYNCPG-SUPABASE-FIX (MINOR). Runtime posture unchanged: PAPER ONLY, no activation guards flipped, no execution path touched.

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
- WARP/CRUSADERBOT-PHASE5C-PRESETS -- MAJOR / NARROW INTEGRATION. Strategy preset system: 5 named presets (whale_mirror / signal_sniper / hybrid / value_hunter / full_auto) replace raw strategy picker. SENTINEL APPROVED 92/100. Zero critical issues. Forge: projects/polymarket/crusaderbot/reports/forge/crusaderbot-phase5c-presets.md. Sentinel: projects/polymarket/crusaderbot/reports/sentinel/phase5bc-preset-dashboard.md. Awaiting WARP🔹CMD merge decision on PR #925.
- Phase 5B dashboard hierarchy redesign -- STANDARD / DASHBOARD DISPLAY ONLY. Hierarchy layout, four sections, /start routing. SENTINEL APPROVED 97/100 (focused audit, explicit WARP🔹CMD request). Branch name mismatch (claude/ vs WARP/CRUSADERBOT-PHASE5B-DASHBOARD) — WARP🔹CMD to resolve at merge. Forge: projects/polymarket/crusaderbot/reports/forge/crusaderbot-phase5b-dashboard.md. Sentinel: projects/polymarket/crusaderbot/reports/sentinel/phase5bc-preset-dashboard.md. Awaiting WARP🔹CMD merge decision on PR #926.
- WARP/CRUSADERBOT-ASYNCPG-SUPABASE-FIX -- MINOR / NARROW INTEGRATION FORGE. Resolves Sentry DAWN-SNOWFLAKE-1729-G/J/P/Q. Forge report: projects/polymarket/crusaderbot/reports/forge/asyncpg-supabase-fix.md. Awaiting WARP🔹CMD review + merge decision. Supersedes PR #922.
- Phase 5A global-handlers -- MINOR / NARROW INTEGRATION FORGE. _text_router priority fix (menu buttons clear awaiting state and route before activation/setup consumers). Main menu reduced from 8 to 5 buttons (Dashboard, Auto-Trade, Wallet, My Trades, Emergency). /settings command registered. my_trades combined view added. 784/784 tests green. Forge report: projects/polymarket/crusaderbot/reports/forge/crusaderbot-phase5a-global-handlers.md. Awaiting WARP🔹CMD review + merge decision.

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
- WARP🔹CMD merge decision on PR #925 (Phase 5C presets, MAJOR, SENTINEL APPROVED 92/100). Source: projects/polymarket/crusaderbot/reports/sentinel/phase5bc-preset-dashboard.md.
- WARP🔹CMD merge decision on PR #926 (Phase 5B dashboard, STANDARD, SENTINEL APPROVED 97/100). Resolve branch name posture (claude/ vs WARP/) at merge. Source: projects/polymarket/crusaderbot/reports/sentinel/phase5bc-preset-dashboard.md.
- WARP🔹CMD review + merge decision on Phase 5A global-handlers (MINOR). Source: projects/polymarket/crusaderbot/reports/forge/crusaderbot-phase5a-global-handlers.md. No SENTINEL required.
- WARP🔹CMD review + merge decision on WARP/CRUSADERBOT-ASYNCPG-SUPABASE-FIX (MINOR). Source: projects/polymarket/crusaderbot/reports/forge/asyncpg-supabase-fix.md. Resolves recurring production /health DB flap. Close PR #922 as superseded once merged.
- Dispatch WARP/CRUSADERBOT-MAINNET-ONCHAIN-PREFLIGHT as the next safety lane before any owner live-trading decision. Tier: MAJOR, SENTINEL REQUIRED. Scope: read-only wallet/chain/preflight only, no order submission, no guard flips.
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
