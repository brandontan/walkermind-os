Last Updated : 2026-05-12 10:30
Status       : Signal Scan Engine MERGED PR #991 (2026-05-12). Hotfix SQL + emergency guard built; PR open. Production PAPER ONLY. Activation guards remain OFF.

[COMPLETED]
- Fast Track Premium PNL Insights UX MERGED PR #965 (2026-05-11). /insights command, insights_kb, dashboard:insights sub, my_trades nav update, mode=paper boundary on all queries, _safe_md title escaping, best_pnl sign fix; 22 hermetic tests green; issue #963 closed.
- Track G UI Premium Pack 1 built (2026-05-12). animated_entry_sequence (4-step edit flow, 1.2s delays, edit+send fallbacks), /market {slug} rich market card, market_card_kb 2x2 inline keyboard, get_market_by_slug Gamma slug lookup; 21 hermetic tests green; PR open.
- Fast Track Week 2 Track F -- Live Opt-In Gate implemented (2026-05-12). 3-step /enable_live Telegram gate; 4-guard read-only check; mode_change_events audit log (migration 021); auto-fallback 60s monitor; 20 hermetic tests green; MERGED PR #970; issue #968 closed.
- Track H Portfolio Charts + Insights MERGED PR #979 (2026-05-12). /chart PNG photo via matplotlib; chart:7/30/all period callbacks; /insights weekly category+signal breakdown; weekly_insights cron Monday 08:00 WIB; had_pre_window_rows carry-forward fix; 30 hermetic tests green; STANDARD, NARROW INTEGRATION.
- Track I -- Referral + Share System built (2026-05-11). referral_codes/referral_events/fees/fee_config tables (migration 022); /referral command; deep-link join wiring on /start; [Share] button on winning trade notifications; share card handler; fee logic gated (FEE_COLLECTION_ENABLED=False); referral payout gated (REFERRAL_PAYOUT_ENABLED=False); 18 hermetic tests; PR open.
- Track L -- Onboarding Polish built (2026-05-11). /start 2-step flow (Welcome → Mode Select → Paper/Live); /help categorized (TRADING/PORTFOLIO/SETTINGS/ADMIN); ADMIN section operator-gated; 5 command aliases (/scan /pnl /close /trades /mode); 15 hermetic tests green; STANDARD, PRESENTATION.
- MomentumReversalStrategy adapter MERGED PR #978 (2026-05-11). Scan contract, registry bootstrap, STRATEGY_AVAILABILITY updated (momentum_reversal: balanced+aggressive); 50 hermetic tests green; issue #975 closed. STANDARD, NARROW INTEGRATION.
- Track J Multi-User Isolation Audit MERGED PR #988 (2026-05-12). 120+ queries audited; zero isolation violations; 24 hermetic tests green; WARP•SENTINEL APPROVED 98/100, zero critical issues; MAJOR, FULL RUNTIME INTEGRATION.
- UX Overhaul Premium Grade MERGED PR #989 (2026-05-12). 9-part Telegram UX redesign; main menu, TP/SL presets, capital presets, strategy cards, settings hub, copy trade fallback, insights fix, my trades format; 45 hermetic tests green; STANDARD, PRESENTATION.
- Signal Scan Engine MERGED PR #991 (2026-05-12). market_signal_scanner job (60s), hourly_report cron, /health operator command, migration 024 seeded demo feed/market/publication; WARP•SENTINEL APPROVED 90/100; MAJOR, FULL RUNTIME INTEGRATION.

[IN PROGRESS]
- Hotfix SQL + emergency guard: PR open on WARP/HOTFIX-SIGNAL-SCAN-SQL. STANDARD, NARROW INTEGRATION. Fixed ABS(AVG()) FILTER SQL error in pnl_insights + added BadRequest guard in emergency_callback. Awaiting WARP🔹CMD review.
- Hotfix legacy UX handler cleanup: PR open on WARP/HOTFIX-UX-OVERHAUL-HANDLERS. STANDARD, PRESENTATION. Removed legacy TP/SL and capital text prompts; STRATEGY_DISPLAY_NAMES applied. 99 hermetic tests green. Awaiting WARP🔹CMD review.
- Track K Access Tiers + Admin Panel: PR open on WARP/CRUSADERBOT-FAST-ADMIN. STANDARD, FOUNDATION. 29 hermetic tests green. Awaiting WARP🔹CMD review.
- Track G UI Premium Pack 1: PR open, WARP🔹CMD review required.
- Track I -- Referral + Share System: PR open, WARP🔹CMD review required. Tier: STANDARD.
- Observation / runtime monitoring remains active in paper mode.
- Current production posture: Telegram @CrusaderBot live, Fly.io app running, Supabase project ykyagjdeqcgcktnpdhes, test user walk3r69 has $1000 paper USDC and Full Auto aggressive preset. access_tier promoted to 3, enrolled in signal_following, subscribed to demo feed (migration 024).
- Activation guards remain OFF: ENABLE_LIVE_TRADING=false, EXECUTION_PATH_VALIDATED=false, CAPITAL_MODE_CONFIRMED=false, RISK_CONTROLS_VALIDATED=false.

[NOT STARTED]
- Wire share_trade_kb into trade close call sites (notify_tp_hit callers in trade_engine/signal_scan) when PNL > 0 — surface ready, wiring deferred.
- Referral payout activation: separate lane, requires WARP🔹CMD decision.
- Fee collection activation: separate lane, requires WARP🔹CMD decision.
- Wire @require_access_tier('PREMIUM') onto trading command handlers (separate lane).
- Seed boss user ADMIN tier row in user_tiers (can be done via /admin settier post-deploy).
- Fast Track Week 4 -- Closed beta observation; no new feature PRs planned in that week.
- Before-live hardening: add AND user_id=$N guard to position_id-only UPDATEs in domain/positions/registry.py (update_current_price line 200, record_close_failure line 215, reset_close_failure line 229, finalize_close_failed line 250) and domain/execution/paper.py close_position UPDATE line 114. Required before ENABLE_LIVE_TRADING activation; safe to defer for PAPER ONLY posture.

[NEXT PRIORITY]
- WARP🔹CMD review required for Hotfix SQL + emergency guard (ACTIVE Sentry bug). Source: projects/polymarket/crusaderbot/reports/forge/hotfix-signal-scan-sql.md. Tier: STANDARD.
- WARP🔹CMD review required for Hotfix legacy UX handler cleanup. Source: projects/polymarket/crusaderbot/reports/forge/forge-hotfix-ux-handlers.md. Tier: STANDARD.
- WARP🔹CMD review required for Track K Access Tiers + Admin Panel PR. Source: projects/polymarket/crusaderbot/reports/forge/access-tiers-admin-panel.md. Tier: STANDARD.
- WARP🔹CMD review required for Track L Onboarding Polish PR. Source: projects/polymarket/crusaderbot/reports/forge/onboarding-polish.md. Tier: STANDARD.
- WARP🔹CMD review required for Track G UI Premium Pack 1. Source: projects/polymarket/crusaderbot/reports/forge-fast-ui-premium-1.md. Tier: STANDARD.
- WARP🔹CMD review required for Track I Referral + Share System. Source: projects/polymarket/crusaderbot/reports/forge/fast-referral.md. Tier: STANDARD.
- Seed ADMIN tier for walk3r69 via /admin settier so hourly_report fires to ADMIN users (migration 024 deployed by PR #991).
- Do not flip activation guards.
- Keep production PAPER ONLY until explicit owner live activation decision.

[KNOWN ISSUES]
- /deposit has no tier gate; intentional and non-blocking.
- check_alchemy_ws is TCP-only and does not perform a full WebSocket handshake; low-priority follow-up.
- ENABLE_LIVE_TRADING code default in config.py is True (legacy); fly.toml [env] overrides to false so production posture is correct. Code default alignment remains deferred to WARP/config-guard-default-alignment.
- integrations/polymarket.py _build_clob_client() is dead in the live execution path after Phase 4B but still indirectly referenced by submit_live_redemption(); cleanup deferred to WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP.
- Activation guards remain NOT SET and must not be changed without explicit owner decision.
- R13 backlog is post-MVP growth work and not required for current paper-safe runtime.
- [DEFERRED] Concurrent HALF_OPEN trial race in CircuitBreaker._record_failure may multiply on_open invocations and restart cool-down; P2, no safety implication.
- [DEFERRED] CLOB circuit-open Telegram alert text uses plain markdown rather than MarkdownV2; P2, acceptable for static template.
- [DEFERRED] Ops dashboard CLOB circuit card refreshes only via page-level 30s meta refresh; SSE/WS push is future enhancement.
- [DEFERRED] Package-level single-instance CircuitBreaker is adequate for single-broker steady state; per-broker instances can be passed via circuit_breaker kwarg if needed.
- [DEFERRED] Forge report Known Issues section for Track D references stale parity patch approach (gate.get_settings); code is correct post-Codex fix; documentation drift only.
- [DEFERRED] check_price_deviation() not yet wired into live execution path; callable and tested; deferred until ENABLE_LIVE_TRADING gate is considered.
- [DEFERRED] auto_fallback.py: audit event written after mode switch, not before — found in PR #970 CRUSADERBOT-FAST-LIVE-GATE.
- [DEFERRED] live_gate.py: AWAITING_STEP2 not proactively expired if Step 3 button never pressed — found in PR #970 CRUSADERBOT-FAST-LIVE-GATE.
- [DEFERRED] No asyncio.timeout on polymarket.get_markets() in market_signal_scanner.py; scanner stall risk on hung HTTP call; P2, no capital impact — found in PR #991 SIGNAL-SCAN-ENGINE.
- [DEFERRED] Migration 024 blast radius understated as test-user-only in forge report; SQL promotes all users; documentation drift, code is correct — found in PR #991 SIGNAL-SCAN-ENGINE.
