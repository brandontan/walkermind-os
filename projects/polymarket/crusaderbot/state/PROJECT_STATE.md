Last Updated : 2026-05-14 22:16
Status       : telegram-ux-v5-autobot V5 AUTOBOT UI overhaul built; PR open on claude/forge-task-1044-V5D08 awaiting WARP🔹CMD review. Production PAPER ONLY. Activation guards remain OFF / NOT SET.

[COMPLETED]
- live-execution-user-id-guards MERGED PR #1021. close_position() AND user_id=$N hardening; 5 isolation tests; MAJOR, NARROW INTEGRATION. WARP•SENTINEL APPROVED 97/100.
- compact-hierarchy-readability-regression MERGED PR #1032 on warp/fix-telegram-mvp-ux-readability-regression. Compact hierarchy readability regression fix + traceability/state sync; STANDARD, NARROW INTEGRATION.
- Premium UX v4 (Hybrid Luxury) — PR #1026 merged bd8fe42d
- Telegram UX v3 MERGED PR #1024 (2026-05-13). 7-button menu (Dashboard/Portfolio/Auto Mode/Signals/Insights/Settings/Stop Bot), dashboard v3 with smart CTA, portfolio screen, signals tap-hub (inline feed toggle, no CLI), settings hub v3, onboarding v3, nav_row() helper, notifications.py utility. STANDARD, NARROW INTEGRATION.
- Migration idempotency fix MERGED PR #1003 (2026-05-12). ON CONFLICT DO NOTHING for signal_feeds seeds in migrations 024/025; run_migrations() per-file error logging; fixes DAWN-SNOWFLAKE-1729-2 and -3. MAJOR, NARROW INTEGRATION.
- Telegram inline UI restore + paper autotrade smoke MERGED PR #999 (2026-05-12). ConversationHandler fallback menu button sets patched in copy_trade.py and presets.py to match UX Overhaul layout; health.py job count corrected to 17; paper path smoke verified by code inspection; issue #998 closed. STANDARD, NARROW INTEGRATION.
- P1 user_id isolation hardening MERGED PR #997 (2026-05-12). AND user_id=$N added to 5 UPDATE statements across registry.py and paper.py; exit_watcher call sites updated. STANDARD, NARROW INTEGRATION.
- WARP Auto Gate v1 MERGED PR #996 (2026-05-12). warp-auto-gate.yml + warp_auto_gate.py; Gates 1-8 + CI status; idempotent PR comment. STANDARD, NARROW INTEGRATION.
- Hotfix /insights UndefinedColumnError strategy_type MERGED PR #995 (2026-05-12). LEFT JOIN orders in weekly_insights signal breakddown fixes DAWN-SNOWFLAKE-1729-10 and DAWN-SNOWFLAKE-1729-Z.
- Signal Scan Engine MERGED PR #991 (2026-05-12). market_signal_scanner, hourly_report, /health, migration 024; WARP•SENTINEL APPROVED 90/100; MAJOR, FULL RUNTIME INTEGRATION.
- UX Overhaul Premium Grade MERGED PR #989 (2026-05-12). Telegram UX redesign; 45 hermetic tests green; STANDARD, PRESENTATION.
- Track J Multi-User Isolation Audit MERGED PR #988 (2026-05-12). WARP•SENTINEL APPROVED 98/100; zero critical isolation issues.
- Track H Portfolio Charts + Insights MERGED PR #979 (2026-05-12). /chart PNG, chart period callbacks, /insights weekly breakddown, weekly_insights cron; 30 hermetic tests green.
- MomentumReversalStrategy adapter MERGED PR #978 (2026-05-11). Strategy registry bootstrap and STRATEGY_AVAILABILITY updated; 50 hermetic tests green.
- Fast Track Week 2 Track F -- Live Opt-In Gate MERGED PR #970 (2026-05-12). /enable_live 3-step gate, mode_change_events audit log, auto-fallback monitor; activation guards remain OFF.

[IN PROGRESS]
- telegram-ux-v5-autobot: V5 AUTOBOT UI overhaul — CRUSADER|AUTOBOT branding, pulse line, HTML code-wrapped financials, 6-button main menu, routing sync, onboarding branding, preset wizard label sync; PR open on claude/forge-task-1044-V5D08; STANDARD, NARROW INTEGRATION. Source: projects/polymarket/crusaderbot/reports/forge/claude-forge-task-1044-V5D08.md
- telegram-premium-polish: Hybrid Luxury premium polish for telegram templates/keyboards + settings placeholder stubs + noop refresh rerender; PR open on warp/polish-telegram-bot-templates-and-keyboards-07rpb4; STANDARD, NARROW INTEGRATION. Source: projects/polymarket/crusaderbot/reports/forge/warp-polish-telegram-bot-templates-and-keyboards-07rpb4.md
- telegram-ux-polish: UX cleanup — Dashboard button main menu, edit vs reply nav, dashboard text W/L clarity, keyboard nav dedup, activity nav keyboard, settings risk display fix; PR open on WARP/telegram-ux-polish; STANDARD, NARROW INTEGRATION. Source: projects/polymarket/crusaderbot/reports/forge/telegram-ux-polish.md
- crusaderbot-telegram-redesign-v2: Gate fixes applied — positions.py stats clarity fix, settings.py Python 3.11 f-string lint fix; PR #1036 on warp/redesign-telegram-ux-for-crusaderbot; ruff PASS; STANDARD, NARROW INTEGRATION. Source: projects/polymarket/crusaderbot/reports/forge/crusaderbot-telegram-redesign-v2.md
- crusaderbot-mvp-reset-v1: Telegram MVP UX reset complete; PR open on WARP/crusaderbot-mvp-reset-v1 awaiting WARP🔹CMD review; STANDARD, NARROW INTEGRATION. Source: projects/polymarket/crusaderbot/reports/forge/crusaderbot-mvp-reset-v1.md
- telegram-lightweight-tree-ui-hotfix: final lightweight tree UI replacement pass; PR #1034 open on WARP/telegram-lightweight-tree-ui-hotfix; STANDARD, NARROW INTEGRATION. Source: projects/polymarket/crusaderbot/reports/forge/telegram-lightweight-tree-ui-hotfix.md
- relax-branch-prefix-rule: AGENTS.md updated; PR open, awaiting WARP🔹CMD review. Source: projects/polymarket/crusaderbot/reports/forge/relax-branch-prefix-rule.md
- Observation / runtime monitoring remains active in paper mode.
- Current production posture: Telegram @CrusaderBot live, Fly.io app running, PAPER ONLY.
- Test user walk3r69 has $1000 paper USDC, Full Auto aggressive preset, access_tier promoted to 3, enrolled in signal_following, subscribed to demo feed.
- Activation guards remain OFF: ENABLE_LIVE_TRADING=false, EXECUTION_PATH_VALIDATED=false, CAPITAL_MODE_CONFIRMED=false, RISK_CONTROLS_VALIDATED=false.

[NOT STARTED]
- Wire share_trade_kb into trade close call sites when PNL > 0; surface ready, wiring deferred.
- Referral payout activation: separate lane, requires WARP🔹CMD decision.
- Fee collection activation: separate lane, requires WARP🔹CMD decision.
- Wire @require_access_tier('PREMIUM') onto trading command handlers as separate lane.
- Seed boss user ADMIN tier row in user_tiers via /admin settier post-deploy.
- Fast Track Week 4 -- Closed beta observation; no new feature PRs planned in that week.

[NEXT PRIORITY]
- WARP🔹CMD review required for claude/forge-task-1044-V5D08. STANDARD tier. V5 AUTOBOT branding, pulse line, HTML financials, 6-button menu, routing sync. Source: projects/polymarket/crusaderbot/reports/forge/claude-forge-task-1044-V5D08.md
- WARP🔹CMD review required for warp/polish-telegram-bot-templates-and-keyboards-07rpb4. STANDARD tier. Premium copy polish, placeholder stubs, refresh rerender callback. Source: projects/polymarket/crusaderbot/reports/forge/warp-polish-telegram-bot-templates-and-keyboards-07rpb4.md
- Keep production PAPER ONLY until explicit owner live activation decision.

[KNOWN ISSUES]
- pnl_insights.py, copy_trade.py, portfolio_chart.py still contain ━━━ — out-of-scope for crusaderbot-mvp-ux-v1; separate cleanup lane required.
- /deposit has no tier gate; intentional and non-blocking.
- check_alchemy_ws is TCP-only and does not perform a full WebSocket handshake; low-priority follow-up.
- ENABLE_LIVE_TRADING code default in config.py is True (legacy); fly.toml [env] overrides to false so production posture is correct. Code default alignment remains deferred to WARP/config-guard-default-alignment.
- integrations/polymarket.py _build_clob_client() is dead in the live execution path after Phase 4B but still indirectly referenced by submit_live_redemption(); cleanup deferred to WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP.
- Activation guards remain NOT SET and must not be changed without explicit owner decision.
- R13 backlog is post-MVP growth work and not required for current paper-safe runtime.
- [DEFERRED] No asyncio.timeout on polymarket.get_markets() in market_signal_scanner.py; scanner stall risk on hung HTTP call; P2, no capital impact.
- [DEFERRED] Migration 024 blast radius understated as test-user-only in forge report; SQL promotes all users; documentation drift, code is correct.
