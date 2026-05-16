Last Updated : 2026-05-16 07:03
Status       : WARP/CRUSADERBOT-PHASE5-UX-REBUILD MERGED PR #1055 (2026-05-16). 6 screens rebuilt clean (dark theme, gold CTAs, monospace ledger blocks). group=-1 global nav fix applied. presets.py + messages.py extracted as dedicated modules. migration 028 adds preset_activated_at. MAJOR, NARROW INTEGRATION. Production PAPER ONLY.

[COMPLETED]
- WARP/CRUSADERBOT-PHASE5-UX-REBUILD MERGED PR #1055 (2026-05-16). Full UX rebuild: 6 screens, group=-1 nav fix, presets.py, messages.py, migration 028. ruff+compileall clean. MAJOR, NARROW INTEGRATION.
- crusaderbot-ux-bugfix complete (2026-05-15). 5 UX bugs: autotrade_toggle_cb dashboard refresh, trades nav_row, insights_kb nav, Active Monitor dedicated view, startup /tmp lock cooldown, /resetonboard admin command, curly-quote audit (zero hits). ruff+compileall clean. STANDARD, NARROW INTEGRATION.
- crusaderbot-operator-hotfix complete (2026-05-15). Replaced 6 "operator guards" occurrences with "activation guards" across main.py, api/admin.py, api/health.py. Display strings + log + docstring. Validation grep → zero hits. MINOR, FOUNDATION.
- mvp-cleanup complete (2026-05-15). ParseMode.MARKDOWN/V2 → HTML across 17 handler files + notifier + domain/activation. html.escape() on all external variables. operator→admin in 5 files. 24 .bak files deleted. 3 dead legacy keyboard functions removed. ruff+compileall clean. STANDARD, NARROW INTEGRATION.
- crusaderbot-ux-patch-1 PR open (2026-05-15). Startup message OPERATOR_CHAT_ID guard + bot-ON ReplyKeyboard layout fix (Active Monitor/Portfolio+Settings/Emergency). _MENU_BUTTONS updated. 74 hermetic UX tests green. MINOR, NARROW INTEGRATION.
- crusaderbot-mvp-runtime-ux MERGED PR #1049 (2026-05-15). 5-preset system (whale_mirror+hybrid added), capital decoupling via capital_for_risk_profile(), state-driven main_menu() 3-layout, HTML blockquote UX throughout, copy-trade pipeline completion, scanner state exposure, tier wording cleanup. Closes #1036, #1034. MAJOR, FULL RUNTIME INTEGRATION. 1405 tests green.
- V5 "AUTOBOT" UI Overhaul MERGED PR #1045. Dashboard pulse, monospaced financials, 6-button menu, English localization. STANDARD, NARROW INTEGRATION.
- live-execution-user-id-guards MERGED PR #1021. close_position() AND user_id=$N hardening; 5 isolation tests; MAJOR, NARROW INTEGRATION. WARP•SENTINEL APPROVED 97/100.
- compact-hierarchy-readability-regression MERGED PR #1032 on warp/fix-telegram-mvp-ux-readability-regression. Compact hierarchy readability regression fix + traceability/state sync; STANDARD, NARROW INTEGRATION.
- Premium UX v4 (Hybrid Luxury) — PR #1026 merged bd8fe42d. STANDARD, NARROW INTEGRATION.

[IN PROGRESS]
- Closed beta observation / paper-mode runtime monitoring active.
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
- Apply migration 028 (preset_activated_at) to production before deploying Phase 5 code to Fly.io.
- Apply migration 027 (notifications_on) to production before deploying to Fly.io.
- WARP🔹CMD review required: crusaderbot-ux-bugfix (STANDARD). Report: projects/polymarket/crusaderbot/reports/forge/crusaderbot-ux-bugfix.md.
- Deploy merged changes to Fly.io production (PAPER ONLY — activation guards remain OFF).

[KNOWN ISSUES]
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
