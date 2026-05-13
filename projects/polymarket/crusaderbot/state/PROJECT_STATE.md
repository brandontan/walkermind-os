Last Updated : 2026-05-13 19:00 WIB
Status       : compact hierarchy traceability/state sync lane active for PR #1032 on warp/fix-telegram-mvp-ux-readability-regression. PR #1029 and #1031 merged. Production PAPER ONLY. Activation guards remain OFF / NOT SET.

[COMPLETED]
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
- telegram-compact-hierarchy-ui: compact hierarchy UI readability pass in handlers/keyboards; STANDARD, NARROW INTEGRATION. Source: projects/polymarket/crusaderbot/reports/forge/telegram-compact-hierarchy-ui.md
- compact-hierarchy-readability-regression: PR #1032 open on warp/fix-telegram-mvp-ux-readability-regression for compact hierarchy readability regression fix and traceability/state sync. Source: projects/polymarket/crusaderbot/reports/forge/telegram-compact-hierarchy-ui.md
- relax-branch-prefix-rule: AGENTS.md updated; PR open, awaiting WARP🔹CMD review. Source: projects/polymarket/crusaderbot/reports/forge/relax-branch-prefix-rule.md
- live-execution-user-id-guards: WARP•SENTINEL APPROVED 97/100. PR #1021 open. Awaiting WARP🔹CMD merge decision. Source: projects/polymarket/crusaderbot/reports/sentinel/live-execution-user-id-guards.md
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
- WARP🔹CMD re-review required for PR #1032 (compact hierarchy readability regression fix) on warp/fix-telegram-mvp-ux-readability-regression. STANDARD tier. Source: projects/polymarket/crusaderbot/reports/forge/telegram-compact-hierarchy-ui.md
- WARP🔹CMD review required for relax-branch-prefix-rule PR. STANDARD tier. Source: projects/polymarket/crusaderbot/reports/forge/relax-branch-prefix-rule.md
- WARP🔹CMD merge decision for live-execution-user-id-guards PR #1021. SENTINEL APPROVED 97/100. Source: projects/polymarket/crusaderbot/reports/sentinel/live-execution-user-id-guards.md
- After merge: open WARP/notifications-paper-wire to wire notify_order_filled() into paper executor.
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
- [DEFERRED] CHANGELOG.md entry missing for WARP/live-execution-user-id-guards — append on post-merge sync.
- [DEFERRED] NEXT PRIORITY 4 items in PR #1021 PROJECT_STATE.md (cap 3) — prune on post-merge sync.

