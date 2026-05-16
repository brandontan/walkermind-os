Last Updated : 2026-05-16 23:59
Status       : trading-unblock MERGED PR #1065. Apply migration 030 + deploy to unblock 5 expired positions. Signal scan fires immediately on startup. Production PAPER ONLY.

[COMPLETED]
- trading-unblock MERGED PR #1065 (2026-05-16). exit_watcher two-phase MARKET_EXPIRED sweep: Phase A 3-tick None-price threshold, Phase B list_open_on_resolved_markets(); close_as_expired() atomic tx; alert_user_market_expired(); RunResult; signal scan next_run_time=now; job_runs metadata JSONB. MAJOR, NARROW INTEGRATION.
- WARP/CRUSADERBOT-AUTOTRADE-RUNTIME MERGED PR #1061 (2026-05-16). exit_watcher live Gamma price fetch + pnl_usdc persistence + signal_scan open-position dedup guard + WebTrader YES/NO badges and date+time display. MAJOR, FULL RUNTIME INTEGRATION.
- WARP/CRUSADERBOT-WEBTRADER-REDESIGN PR open (2026-05-16). WebTrader premium frontend redesign: Syne + JetBrains Mono fonts, new dark palette (#080A0F bg, gold #F5C842 accent), 5 pages + 5 components reskinned, Recharts PnL chart, ambient gradients, fadeSlideUp transitions. npm build clean. STANDARD, NARROW INTEGRATION.
- WARP/CRUSADERBOT-WEBTRADER MERGED PR #1058 (2026-05-16). WebTrader browser dashboard: migration 029 (portfolio_snapshots, system_alerts, NOTIFY triggers), FastAPI SSE backend (asyncpg LISTEN/NOTIFY fan-out), JWT auth (Telegram Login Widget), React/Vite/Tailwind SPA (6 pages, 7 components), multi-stage Dockerfile. MAJOR, NARROW INTEGRATION.
- deploy-test-report complete (2026-05-16). Test suite 1398 pass, 1 skip. UX 6 screens static analysis: all pass. fly CLI not available — deploy not executed. STANDARD, NARROW INTEGRATION.
- WARP/CRUSADERBOT-PHASE5-FIX-R1 PR open (2026-05-16). 3 UX bugs: COPY CODE removed from dashboard/autotrade/trades screens; persistent 5-button ReplyKeyboard (main_menu_keyboard); My Trades show_trades DB error hardened with try/except + group=-1 handler. 119 tests green. STANDARD, NARROW INTEGRATION.
- WARP/CRUSADERBOT-PHASE5-UX-REBUILD MERGED PR #1055 (2026-05-16). Full UX rebuild: 6 screens, group=-1 nav fix, presets.py, messages.py, migration 028. ruff+compileall clean. MAJOR, NARROW INTEGRATION.
- crusaderbot-ux-bugfix complete (2026-05-15). 5 UX bugs: autotrade_toggle_cb dashboard refresh, trades nav_row, insights_kb nav, Active Monitor dedicated view, startup /tmp lock cooldown, /resetonboard admin command, curly-quote audit (zero hits). ruff+compileall clean. STANDARD, NARROW INTEGRATION.
- crusaderbot-operator-hotfix complete (2026-05-15). Replaced 6 "operator guards" occurrences with "activation guards" across main.py, api/admin.py, api/health.py. MINOR, FOUNDATION.
- mvp-cleanup complete (2026-05-15). ParseMode.MARKDOWN/V2 → HTML across 17 handler files. STANDARD, NARROW INTEGRATION.
- crusaderbot-mvp-runtime-ux MERGED PR #1049 (2026-05-15). 5-preset system, capital decoupling, state-driven menu, HTML blockquote UX, copy-trade pipeline. MAJOR, FULL RUNTIME INTEGRATION. 1405 tests green.
- V5 "AUTOBOT" UI Overhaul MERGED PR #1045. STANDARD, NARROW INTEGRATION.

[IN PROGRESS]
- Closed beta observation / paper-mode runtime monitoring active.
- Current production posture: Telegram @CrusaderBot live, Fly.io app running, PAPER ONLY.
- Test user walk3r69 has $1000 paper USDC, Full Auto aggressive preset, access_tier promoted to 3, enrolled in signal_following, subscribed to demo feed.
- trading-unblock merged — awaiting migration 030 apply + deploy. 5 stuck positions will auto-close within 1 exit_watch tick (60s) after deploy.
- Activation guards remain OFF: ENABLE_LIVE_TRADING=false, EXECUTION_PATH_VALIDATED=false, CAPITAL_MODE_CONFIRMED=false, RISK_CONTROLS_VALIDATED=false.

[NOT STARTED]
- Apply migration 030 (job_runs metadata JSONB) to production before deploying trading-unblock.
- Apply migration 029 (portfolio_snapshots, system_alerts, NOTIFY triggers) to production before deploying WARP/CRUSADERBOT-WEBTRADER.
- Set fly secret WEBTRADER_JWT_SECRET=<openssl rand -hex 32> before deploying WebTrader.
- Register crusaderbot.fly.dev domain in BotFather: /setdomain @CrusaderBot crusaderbot.fly.dev (required for Telegram Login Widget).
- migration 027 (notifications_on) must be applied before deploying crusaderbot-mvp-runtime-ux to production.
- Wire share_trade_kb into trade close call sites when PNL > 0; surface ready, wiring deferred.
- Referral payout activation: separate lane, requires WARP🔹CMD decision.
- Fee collection activation: separate lane, requires WARP🔹CMD decision.
- Wire @require_access_tier('PREMIUM') onto trading command handlers as separate lane.
- Seed boss user ADMIN tier row in user_tiers via /admin settier post-deploy.
- Fast Track Week 4 -- Closed beta observation; no new feature PRs planned in that week.

[NEXT PRIORITY]
- Apply migration 030 (job_runs metadata JSONB) to production, then deploy trading-unblock (PR #1065 merged). 5 expired positions auto-close on first exit_watch tick.
- WARP🔹CMD review required for webtrader-redesign (STANDARD). Source: projects/polymarket/crusaderbot/reports/forge/webtrader-redesign.md. Tier: STANDARD.
- WARP•SENTINEL validation required for webtrader-dashboard (MAJOR) before production deploy — PR #1058 merged to main. Source: projects/polymarket/crusaderbot/reports/forge/webtrader-dashboard.md.

[KNOWN ISSUES]
- 5 positions stuck open — trading-unblock PR #1065 merged; will close within 1 exit_watch tick (60s) once migration 030 applied and deployed.
- fly CLI not installed in cloud execution environment — deploy step requires WARP🔹CMD manual execution from fly CLI machine.
- migration 027 (notifications_on) must be applied to production before deploying PR #1049 + PR #1055 code on Fly.io.
- pnl_insights.py, copy_trade.py, portfolio_chart.py still contain ━━━ — out-of-scope for crusaderbot-mvp-runtime-ux; separate cleanup lane required.
- WARP🔹CMD to verify Fly.io production deploy of PR #1049 + PR #1055 changes before activating on Fly.io.
- Keep production PAPER ONLY until explicit owner live activation decision.
- /deposit has no tier gate; intentional and non-blocking.
- check_alchemy_ws is TCP-only and does not perform a full WebSocket handshake; low-priority follow-up.
- ENABLE_LIVE_TRADING code default in config.py is True (legacy); fly.toml [env] overrides to false so production posture is correct. Code default alignment remains deferred to WARP/config-guard-default-alignment.
- integrations/polymarket.py _build_clob_client() is dead in the live execution path after Phase 4B but still indirectly referenced by submit_live_redemption(); cleanup deferred to WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP.
- Activation guards remain NOT SET and must not be changed without explicit owner decision.
- R13 backlog is post-MVP growth work and not required for current paper-safe runtime.
- [DEFERRED] No asyncio.timeout on polymarket.get_markets() in market_signal_scanner.py; scanner stall risk on hung HTTP call; P2, no capital impact.
- [DEFERRED] Migration 024 blast radius understated as test-user-only in forge report; SQL promotes all users; documentation drift, code is correct.
