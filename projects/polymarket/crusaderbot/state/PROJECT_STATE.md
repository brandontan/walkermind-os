Last Updated : 2026-05-10 20:00
Status       : Phase 5G Auto-Trade customize wizard MERGED PR #938. Phase 5H onboarding and Phase 5I My Trades PRs open for WARP🔹CMD review. Runtime posture unchanged: PAPER ONLY, no activation guards flipped, no execution path touched.

[COMPLETED]
- R12 final Fly.io production paper deploy -- Issue #900 closed; production paper deploy complete.
- Phase 4E CLOB Resilience -- PR #919 merged, MAJOR, FULL RUNTIME INTEGRATION, SENTINEL APPROVED 94/100, branch WARP/CRUSADERBOT-PHASE4E-RESILIENCE.
- asyncpg + Supabase Supavisor fix -- PR #923 merged, MINOR, branch WARP/CRUSADERBOT-ASYNCPG-SUPABASE-FIX. Resolves Sentry DAWN-SNOWFLAKE-1729-G/J/P/Q. 822/822 tests green.
- Phase 5A global-handlers -- PR #924 merged, MINOR, declared WARP/CRUSADERBOT-PHASE5A-GLOBAL-HANDLERS. _text_router priority fix, 5-button main menu, /settings command, my_trades view. 784/784 tests green.
- Phase 5C strategy preset system -- PR #925 merged, MAJOR, branch WARP/CRUSADERBOT-PHASE5C-PRESETS, SENTINEL APPROVED 92/100. 3 presets (signal_sniper / value_hunter / full_auto), DB migration 016, paper-only activation enforced. 814/814 tests green.
- Phase 5B dashboard hierarchy redesign -- PR #926 merged, STANDARD, declared WARP/CRUSADERBOT-PHASE5B-DASHBOARD, SENTINEL APPROVED 97/100. Single-message hierarchy, four sections, /start routing for existing Tier 2+ users.
- SENTINEL report Phase 5B + 5C -- PR #927 merged. Report: projects/polymarket/crusaderbot/reports/sentinel/phase5bc-preset-dashboard.md.
- Phase 5D 2-column grid + Copy/Auto Trade menu split -- PR #928 merged, STANDARD. grid_rows() helper, main menu 5→6 buttons, 🐋 Copy Trade entry point, preset trim 5→3. 57/57 Phase 5D + preset tests green.
- Phase 5J emergency menu redesign -- PR #932 merged, STANDARD, WARP•SENTINEL APPROVED 90/100 (0 criticals). Lock Account DB-enforced (migration 017), /unlock operator command, confirmation dialogs, 13 hermetic tests.
- Phase 5E Copy Trade dashboard + wallet discovery -- PR #930 merged, MAJOR, NARROW INTEGRATION, WARP/CRUSADERBOT-PHASE5E-COPY-TRADE. Dashboard empty state + task-list hierarchy, two-path wallet discovery (Paste Address + Discover leaderboard), wallet stats service (Gamma API + 5-min cache + retry+backoff), migration 018, 24 hermetic tests. 903/903 tests green.
- Phase 5F Copy Trade wizard + per-task edit -- PR #935 merged, MAJOR, NARROW INTEGRATION. 3-step wizard, per-task edit, ConversationHandler 5 states, repository CRUD (toggle_pause atomic), 33 hermetic tests. P1 fixes applied (atomicity + user_id guard + asyncio.run() test pattern).
- Phase 5G Auto-Trade customize wizard -- PR #938 merged, STANDARD, NARROW INTEGRATION. 5-step ConversationHandler wizard (capital, TP, SL, skip, review), custom text input with bounds validation, live-mode guard (Codex P1 fix), back/cancel at every step, save writes DB, 23 hermetic tests. Report: projects/polymarket/crusaderbot/reports/forge/customize-wizard.md.

[IN PROGRESS]
- Phase 5I My Trades combined view -- PR open (STANDARD, WARP🔹CMD review, no SENTINEL required). Handler rewrite: combined positions + activity message, per-position close with confirmation, full history pagination, 2-col keyboard grid. 13 hermetic tests. Report: projects/polymarket/crusaderbot/reports/forge/phase5i-my-trades.md.
- Phase 5H first-time onboarding flow -- PR open (STANDARD, WARP🔹CMD review, no SENTINEL required). ConversationHandler 5 states (WELCOME/FAQ/WALLET/STYLE/DEPOSIT), onboarding_complete flag (migration 019), QR code via qrcode[pil], 18 hermetic tests. Report: projects/polymarket/crusaderbot/reports/forge/crusaderbot-phase5h-onboarding.md.

[NOT STARTED]
- Phase 5G copy execution engine -- reads copy_trade_tasks rows with status=active to drive actual position mirroring; no live trading. (Phase 5G UX wizard shipped separately above.)
- WARP/CRUSADERBOT-MAINNET-ONCHAIN-PREFLIGHT -- on-chain wallet, allowance, balance, and signer readiness checks complementing scripts/mainnet_preflight.py; no live trading activation and no real orders.
- WARP/CRUSADERBOT-OPS-CIRCUIT-RESET -- operator endpoint / Telegram command to force_close the CLOB circuit breaker after incident review; no broker calls and no guard flips.
- R13a Leaderboard -- paper P&L ranking, /leaderboard command, top 10, daily scheduler update.
- R13b Backtesting Engine -- replay historical Polymarket data and output win rate, Sharpe ratio, max drawdown, and EV.
- R13c Multi-Signal Fusion -- combine sentiment and on-chain volume into copy-trade signal weighting; MAJOR if strategy execution behavior changes.
- R13d Web Dashboard (Admin) -- React + FastAPI admin views for users, positions, P&L chart, and scheduler status.
- R13e Referral System -- referral code, referee discount, and referral accounting.
- R13f Strategy Marketplace -- tier 4 named strategies, subscription model, and 10% platform take.

[NEXT PRIORITY]
- WARP🔹CMD review required for Phase 5H PR (STANDARD). Source: projects/polymarket/crusaderbot/reports/forge/crusaderbot-phase5h-onboarding.md. Tier: STANDARD.
- WARP🔹CMD review required for Phase 5I PR (STANDARD). Source: projects/polymarket/crusaderbot/reports/forge/phase5i-my-trades.md. Tier: STANDARD.
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

<!-- CD verify: 2026-05-10 20:00 -->
