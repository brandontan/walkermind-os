Last Updated : 2026-05-12 14:00
Status       : Signal Scan Engine MERGED PR #991 (2026-05-12). /insights strategy_type hotfix MERGED PR #995 (2026-05-12). WARP Auto Gate v1 MERGED PR #996 (2026-05-12). P1 user_id isolation hardening PR open (STANDARD). Production remains Telegram + Fly.io live, PAPER ONLY. Activation guards remain OFF.

[COMPLETED]
- Fast Track Premium PNL Insights UX MERGED PR #965 (2026-05-11). /insights command, insights_kb, dashboard:insights sub, my_trades nav update, mode=paper boundary on all queries; 22 hermetic tests green; issue #963 closed.
- Fast Track Week 2 Track F -- Live Opt-In Gate MERGED PR #970 (2026-05-12). /enable_live 3-step gate, mode_change_events audit log, auto-fallback monitor; activation guards remain OFF.
- Track H Portfolio Charts + Insights MERGED PR #979 (2026-05-12). /chart PNG, chart period callbacks, /insights weekly breakdown, weekly_insights cron; 30 hermetic tests green.
- MomentumReversalStrategy adapter MERGED PR #978 (2026-05-11). Strategy registry bootstrap and STRATEGY_AVAILABILITY updated; 50 hermetic tests green.
- Track J Multi-User Isolation Audit MERGED PR #988 (2026-05-12). WARP•SENTINEL APPROVED 98/100; zero critical isolation issues.
- UX Overhaul Premium Grade MERGED PR #989 (2026-05-12). Telegram UX redesign; 45 hermetic tests green; STANDARD, PRESENTATION.
- Signal Scan Engine MERGED PR #991 (2026-05-12). market_signal_scanner, hourly_report, /health, migration 024; WARP•SENTINEL APPROVED 90/100; MAJOR, FULL RUNTIME INTEGRATION.
- Hotfix /insights UndefinedColumnError strategy_type MERGED PR #995 (2026-05-12). LEFT JOIN orders in weekly_insights signal breakdown fixes DAWN-SNOWFLAKE-1729-10 and DAWN-SNOWFLAKE-1729-Z.
- WARP Auto Gate v1 MERGED PR #996 (2026-05-12). warp-auto-gate.yml + warp_auto_gate.py; Gates 1-8 + CI status; idempotent PR comment; STANDARD, NARROW INTEGRATION.
- P1 user_id isolation hardening PR open (WARP/P1-USER-ID-ISOLATION-HARDENING). AND user_id=$N added to 5 UPDATE statements: registry.py update_current_price, record_close_failure, reset_close_failure, finalize_close_failed; paper.py close_position. 3 exit_watcher.py call sites updated. STANDARD, NARROW INTEGRATION.

[IN PROGRESS]
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
- Live execution path user_id guards: domain/execution/live.py has 4 position UPDATEs (lines 309, 328, 343, 361) missing AND user_id=$N. Deferred to WARP/live-execution-user-id-guards; required before ENABLE_LIVE_TRADING activation.

[NEXT PRIORITY]
- WARP🔹CMD review required. Source: projects/polymarket/crusaderbot/reports/forge/p1-user-id-isolation-hardening.md. Tier: STANDARD.
- Continue closed beta observation / paper-mode runtime monitoring.
- Keep production PAPER ONLY until explicit owner live activation decision.

[KNOWN ISSUES]
- /deposit has no tier gate; intentional and non-blocking.
- check_alchemy_ws is TCP-only and does not perform a full WebSocket handshake; low-priority follow-up.
- ENABLE_LIVE_TRADING code default in config.py is True (legacy); fly.toml [env] overrides to false so production posture is correct. Code default alignment remains deferred to WARP/config-guard-default-alignment.
- integrations/polymarket.py _build_clob_client() is dead in the live execution path after Phase 4B but still indirectly referenced by submit_live_redemption(); cleanup deferred to WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP.
- Activation guards remain NOT SET and must not be changed without explicit owner decision.
- R13 backlog is post-MVP growth work and not required for current paper-safe runtime.
- [DEFERRED] No asyncio.timeout on polymarket.get_markets() in market_signal_scanner.py; scanner stall risk on hung HTTP call; P2, no capital impact.
- [DEFERRED] Migration 024 blast radius understated as test-user-only in forge report; SQL promotes all users; documentation drift, code is correct.
