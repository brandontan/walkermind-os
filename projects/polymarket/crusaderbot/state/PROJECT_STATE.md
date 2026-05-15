Last Updated : 2026-05-15 15:30
Status       : MVP post-merge hygiene cleanup complete (WARP/CRUSADERBOT-MVP-CLEANUP). ParseMode HTML migration, operator→admin purge, 24 .bak files deleted, dead keyboard functions removed. Production PAPER ONLY.

[COMPLETED]
- mvp-cleanup complete (2026-05-15). ParseMode.MARKDOWN/V2 → HTML across 17 handler files + notifier + domain/activation. html.escape() on all external variables. operator→admin in 5 files. 24 .bak files deleted. 3 dead legacy keyboard functions removed. ruff+compileall clean. STANDARD, NARROW INTEGRATION.
- crusaderbot-ux-patch-1 PR open (2026-05-15). Startup message OPERATOR_CHAT_ID guard + bot-ON ReplyKeyboard layout fix (Active Monitor/Portfolio+Settings/Emergency). _MENU_BUTTONS updated. 74 hermetic UX tests green. MINOR, NARROW INTEGRATION.
- crusaderbot-mvp-runtime-ux MERGED PR #1049 (2026-05-15). 5-preset system (whale_mirror+hybrid added), capital decoupling via capital_for_risk_profile(), state-driven main_menu() 3-layout, HTML blockquote UX throughout, copy-trade pipeline completion, scanner state exposure, tier wording cleanup. Closes #1036, #1034. MAJOR, FULL RUNTIME INTEGRATION. 1405 tests green.
Last Updated : 2026-05-15 12:20
Status       : CrusaderBot MVP Runtime + Telegram UX Redesign MERGED PR #1049 (14 phases A–N). 5-preset system, capital decoupling, state-driven menu, HTML blockquote UX, copy-trade pipeline, scanner state, tier wording cleanup. Production PAPER ONLY.

[COMPLETED]
- crusaderbot-mvp-runtime-ux MERGED PR #1049 (2026-05-15). MVP Runtime + Telegram UX Redesign — 14 phases A–N. 5-preset system, capital decoupling, state-driven menu, HTML blockquote UX, copy-trade pipeline, scanner state exposure, tier wording cleanup; 58 hermetic tests green; MAJOR, FULL RUNTIME INTEGRATION + UX REDESIGN. Issues #1036 and #1034 closed.
- V5 "AUTOBOT" UI Overhaul MERGED PR #1045. Dashboard pulse, monospaced financials, 6-button menu, English localization. STANDARD, NARROW INTEGRATION.
- live-execution-user-id-guards MERGED PR #1021. close_position() AND user_id=$N hardening; 5 isolation tests; MAJOR, NARROW INTEGRATION. WARP•SENTINEL APPROVED 97/100.
- compact-hierarchy-readability-regression MERGED PR #1032 on warp/fix-telegram-mvp-ux-readability-regression. Compact hierarchy readability regression fix + traceability/state sync; STANDARD, NARROW INTEGRATION.
- Premium UX v4 (Hybrid Luxury) — PR #1026 merged bd8fe42d
- Telegram UX v3 MERGED PR #1024 (2026-05-13). 7-button menu (Dashboard/Portfolio/Auto Mode/Signals/Insights/Settings/Stop Bot), dashboard v3 with smart CTA, portfolio screen, signals tap-hub (inline feed toggle, no CLI), settings hub v3, onboarding v3, nav_row() helper, notifications.py utility. STANDARD, NARROW INTEGRATION.
- Migration idempotency fix MERGED PR #1003 (2026-05-12). ON CONFLICT DO NOTHING for signal_feeds seeds in migrations 024/025; run_migrations() per-file error logging; fixes DAWN-SNOWFLAKE-1729-2 and -3. MAJOR, NARROW INTEGRATION.
- Telegram inline UI restore + paper autotrade smoke MERGED PR #999 (2026-05-12). ConversationHandler fallback menu button sets patched in copy_trade.py and presets.py to match UX Overhaul layout; health.py job count corrected to 17; paper path smoke verified by code inspection; issue #998 closed. STANDARD, NARROW INTEGRATION.
- P1 user_id isolation hardening MERGED PR #997 (2026-05-12). AND user_id=$N added to 5 UPDATE statements across registry.py and paper.py; exit_watcher call sites updated. STANDARD, NARROW INTEGRATION.
- WARP Auto Gate v1 MERGED PR #996 (2026-05-12). warp-auto-gate.yml + warp_auto_gate.py; Gates 1-8 + CI status; idempotent PR comment. STANDARD, NARROW INTEGRATION.
- Hotfix /insights UndefinedColumnError strategy_type MERGED PR #995 (2026-05-12). LEFT JOIN orders in weekly_insights signal breakdown fixes DAWN-SNOWFLAKE-1729-10 and DAWN-SNOWFLAKE-1729-Z.
- Signal Scan Engine MERGED PR #991 (2026-05-12). market_signal_scanner, hourly_report, /health, migration 024; WARP•SENTINEL APPROVED 90/100; MAJOR, FULL RUNTIME INTEGRATION.
- UX Overhaul Premium Grade MERGED PR #989 (2026-05-12). Telegram UX redesign; 45 hermetic tests green; STANDARD, PRESENTATION.
- Track J Multi-User Isolation Audit MERGED PR #988 (2026-05-12). WARP•SENTINEL APPROVED 98/100; zero critical isolation issues.
- Track H Portfolio Charts + Insights MERGED PR #979 (2026-05-12). /chart PNG, chart period callbacks, /insights weekly breakdown, weekly_insights cron; 30 hermetic tests green.
- MomentumReversalStrategy adapter MERGED PR #978 (2026-05-11). Strategy registry bootstrap and STRATEGY_AVAILABILITY updated; 50 hermetic tests green.
- Fast Track Week 2 Track F -- Live Opt-In Gate MERGED PR #970 (2026-05-12). /enable_live 3-step gate, mode_change_events audit log, auto-fallback monitor; activation guards remain OFF.

[IN PROGRESS]
- Closed beta observation / paper-mode runtime monitoring active.
- WARP/CRUSADERBOT-UX-PATCH-1 PR open — awaiting WARP🔹CMD review and merge.

[IN PROGRESS]
- Observation / runtime monitoring remains active in paper mode.
- Current production posture: Telegram @CrusaderBot live, Fly.io app running, PAPER ONLY.
- Test user walk3r69 has $1000 paper USDC, Full Auto aggressive preset, access_tier promoted to 3, enrolled in signal_following, subscribed to demo feed.
- Activation guards remain OFF: ENABLE_LIVE_TRADING=false, EXECUTION_PATH_VALIDATED=false, CAPITAL_MODE_CONFIRMED=false, RISK_CONTROLS_VALIDATED=false.

[NOT STARTED]
- migration 027 (notifications_on) must be applied before deploying crusaderbot-mvp-runtime-ux to production.
- Wire share_trade_kb into trade close call sites when PNL > 0; surface ready, wiring deferred.
- Referral payout activation: separate lane, requires WARP🔹CMD decision.
- Fee collection activation: separate lane, requires WARP🔹CMD decision.
- Wire @require_access_tier('PREMIUM') onto trading command handlers as separate lane.
- Seed boss user ADMIN tier row in user_tiers via /admin settier post-deploy.
- Fast Track Week 4 -- Closed beta observation; no new feature PRs planned in that week.

[NEXT PRIORITY]
- WARP🔹CMD review required: WARP/CRUSADERBOT-MVP-CLEANUP PR (STANDARD, no SENTINEL required). Report: projects/polymarket/crusaderbot/reports/forge/mvp-cleanup.md.
- WARP🔹CMD decision: mode_select_kb() + paper_complete_kb() — delete with tests or retain (flagged in PR).
- WARP🔹CMD decision: tier gate wiring — wire require_access_tier() to handlers or remove tier middleware (Lane D audit in PR description).
- Apply migration 027 (notifications_on) to production before deploying to Fly.io.
- Deploy merged changes to Fly.io production (PAPER ONLY — activation guards remain OFF).

[KNOWN ISSUES]
- migration 027 (notifications_on) must be applied before deploying this lane.
- pnl_insights.py, copy_trade.py, portfolio_chart.py still contain ━━━ — out-of-scope for crusaderbot-mvp-runtime-ux; separate cleanup lane required.
- Deploy migration 027 (notifications_on) to production before activating PR #1049 code on Fly.io.
- WARP🔹CMD to verify Fly.io production deploy of PR #1049 changes (24 source files).
- Keep production PAPER ONLY until explicit owner live activation decision.

[KNOWN ISSUES]
- migration 027 (notifications_on) must be applied before deploying PR #1049 code on Fly.io.
- pnl_insights.py, copy_trade.py, portfolio_chart.py still contain ━━━ — out-of-scope for crusaderbot-mvp-ux-v1; separate cleanup lane required.
- /deposit has no tier gate; intentional and non-blocking.
- check_alchemy_ws is TCP-only and does not perform a full WebSocket handshake; low-priority follow-up.
- ENABLE_LIVE_TRADING code default in config.py is True (legacy); fly.toml [env] overrides to false so production posture is correct. Code default alignment remains deferred to WARP/config-guard-default-alignment.
- integrations/polymarket.py _build_clob_client() is dead in the live execution path after Phase 4B but still indirectly referenced by submit_live_redemption(); cleanup deferred to WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP.
- Activation guards remain NOT SET and must not be changed without explicit owner decision.
- R13 backlog is post-MVP growth work and not required for current paper-safe runtime.
- [DEFERRED] No asyncio.timeout on polymarket.get_markets() in market_signal_scanner.py; scanner stall risk on hung HTTP call; P2, no capital impact.
- [DEFERRED] Migration 024 blast radius understated as test-user-only in forge report; SQL promotes all users; documentation drift, code is correct.
