Last Updated : 2026-05-17 10:48
Status       : autonomous-trading-bot MVP pipeline in progress. Critical onboarding bug fixed (preset activation + auto_trade_on in skip_deposit_cb). Production PAPER ONLY.

[COMPLETED]
- telegram-ux-final-polish PR open (2026-05-17). Wallet copy-address bug fixed (rsplit parse), portfolio_chart tier gate removed, wallet_p5_kb home label corrected, emergency_done_p5_kb auto-trade label corrected, _hub_text unused tier param removed. compileall clean. STANDARD, NARROW INTEGRATION.
- crusaderbot-mvp-runtime-v1 MERGED PR #1080 (2026-05-17). Tier gates removed from all paper paths: scheduler (deposit auto-bump + run_signal_scan filter), signal_scan_job (_load_enrolled_users filter), daily_pnl_summary (access_tier >= 2), weekly_insights (access_tier >= 2), tier_gate.py (no-op passthrough), admin.py (status counts + active_users + broadcast). MAJOR, FULL RUNTIME INTEGRATION.
- signal-scanner-enable MERGED PR #1079 (2026-05-17). Migration 031 feed backfill + user enrollment; signal_scan_job access_tier filter relaxed for paper; users.py _enroll_signal_following on new user creation. STANDARD, NARROW INTEGRATION.
- role-model-admin-user MERGED PR #1076 (2026-05-17). Two-role refactor: risk gate step-3 tier check scoped to LIVE only (paper open to every user); bot/handlers/setup.py _ensure_tier2→_ensure_user (no setup gate); middleware/tier wording collapsed to two canonical messages; admin.py two-role surface (🛠 Admin sections, settier user|admin mapped onto FREE/ADMIN — no migration); assert_live_guards DELIBERATELY UNCHANGED per CLAUDE.md. SENTINEL 97/100. MAJOR, NARROW INTEGRATION.
- crusaderbot-finalize MERGED PR #1075 (2026-05-17). Public-ready paper beta hardening: config.py ENABLE_LIVE_TRADING default flipped True→False (paper-safe; fly.toml prod posture unchanged) + readiness_validator comment; copy_trade.py dead Phase 5F placeholder branches removed + edit_pnl implemented via repository.task_pnl_summary (positions⋈orders idempotency_key scoping); users.user_notifications_enabled + notifications_enabled_by_telegram_id (fail-open) wired into trade_notifications._send and daily_pnl_summary loop; settings.py docstring corrected; scheduler.sweep_deposits CTE COUNT fix + deposit_sweep audit; api/ops.py kill/resume client_host audit breadcrumb + documented deferral; pytest.ini testpaths polyquantbot→crusaderbot; .env.example + DEPLOY.md completed; PRODUCTION_CHECKLIST.md added. 1432 tests pass, ruff clean. SENTINEL 96/100. MAJOR, NARROW INTEGRATION.
- webtrader-v3-and-bot-polish MERGED PR #1069 (2026-05-16). Tactical Terminal v3.2 atomic delivery — frontend: 15 new shared components (TopBar/Ticker/HeroCard/StatCard/StatsGrid/Terminal/PositionCard/EmptyState/Toggle/FilterTabs/WalletCard/AddressCard/SettingsGroup/AdvancedGate + StrategyCard rewrite), UiMode context with localStorage persist, scanline+grain+ambient atmosphere, clip-path HUD geometry, 6 pages rewritten; bot: messages.py EMOJI/DIV/_table + 5 new alert templates (signal/position_open/position_close/daily_summary/health), keyboards/_common.py shared row helpers (home_back_row/confirm_cancel_row/pagination_row), dispatcher.py drops 4 aliases (/pnl /close /scan /mode) + adds _nav_cb for nav:* prefix, keyboards/presets.py + settings.py 2-col mobile cleanup; tests 1400 pass 0 fail; npm build 62 modules clean; ruff clean. Supersedes WARP/CRUSADERBOT-WEBTRADER-REDESIGN. MAJOR, FULL RUNTIME INTEGRATION.
- bot-polish-beta MERGED PR #1068 (2026-05-16). P0: fly.toml immediate deploy strategy + asyncpg max_inactive_connection_lifetime=60s + trades.py/share_card.py market_question→JOIN markets. Area 1: alert_user_market/close_failed user notifs suppressed in exit_watcher; alert_startup dead code + os import deleted from alerts.py; test_health.py refs updated. Area 2: trade notif inline keyboards (notify_entry/tp/sl/manual/emergency) + deposit KB in scheduler.py + dashboard switched to main_menu() state-driven. Area 3: /help admin-scoped; weekly_insights active-only filter; hourly_report JOIN bug fixed (t.user_id=u.id). MAJOR, FULL RUNTIME INTEGRATION.
- startup-logo-fix PR open (2026-05-16). 60s Redis dedup on startup notification; duplicate alert_startup call removed; logo img added to DashboardPage topbar (32px) and AuthPage (80px); public/ dir created. Logo PNG binary pending. STANDARD, NARROW INTEGRATION.
- trading-unblock MERGED PR #1065 (2026-05-16). exit_watcher two-phase MARKET_EXPIRED sweep: Phase A None-price retry, Phase B list_open_on_resolved_markets(); close_as_expired() atomic tx; alert_user_market_expired(); RunResult; signal scan next_run_time=now; job_runs metadata JSONB. MAJOR, NARROW INTEGRATION.
- WARP/CRUSADERBOT-AUTOTRADE-RUNTIME MERGED PR #1061 (2026-05-16). exit_watcher live Gamma price fetch + pnl_usdc persistence + signal_scan open-position dedup guard + WebTrader YES/NO badges and date+time display. MAJOR, FULL RUNTIME INTEGRATION.
- WARP/CRUSADERBOT-WEBTRADER-REDESIGN MERGED PR #1062 (2026-05-16 08:38). WebTrader premium frontend redesign: Syne + JetBrains Mono fonts, new dark palette (#080A0F bg, gold #F5C842 accent), 5 pages + 5 components reskinned, Recharts PnL chart, ambient gradients, fadeSlideUp transitions. npm build clean. Superseded by webtrader-v3-and-bot-polish PR #1069 (Tactical Terminal v3.2). STANDARD, NARROW INTEGRATION.
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
- WARP/CRUSADERBOT-MVP-RUNTIME-V1 branch: Phase 0 audit complete (P0_RUNTIME_MAP.md). Critical bug fix: skip_deposit_cb now applies preset + sets auto_trade_on=True. allowlist_command migrated to is_admin(). PROJECT_STATE merge conflict resolved.
- Closed beta observation / paper-mode runtime monitoring active.
- Current production posture: Telegram @CrusaderPolybot live, Fly.io app running, PAPER ONLY.
- Activation guards remain OFF: ENABLE_LIVE_TRADING=false, EXECUTION_PATH_VALIDATED=false, CAPITAL_MODE_CONFIRMED=false, RISK_CONTROLS_VALIDATED=false.

[NOT STARTED]
- Apply migration 030 (job_runs metadata JSONB) to production before Fly.io deploy (trading-unblock MERGED PR #1065, live on main).
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
- WARP🔹CMD review required for autonomous-trading-bot MVP pipeline. Source: projects/polymarket/crusaderbot/reports/forge/autonomous-trading-bot.md. Tier: MAJOR.
- Apply migration 031 to production DB (idempotent — safe to apply immediately after #1079 merge).
- Apply migration 030 to production. Then deploy main to Fly.io — trading-unblock fix is live on main (MERGED PR #1065).
- WARP•SENTINEL validation required for webtrader-dashboard (MAJOR) before production deploy — PR #1058 merged to main. Source: projects/polymarket/crusaderbot/reports/forge/webtrader-dashboard.md.

[KNOWN ISSUES]
- WARP🔹CMD requested removal of the internal Tier-4/activation-guard LIVE-trading safety gate; WARP•FORGE declined that sub-item only — CLAUDE.md forbids bypassing the live-trading guard. assert_live_guards is intentionally preserved (invisible to users; live remains owner-gated + OFF). All other role-model items delivered as requested.
- Dual tier tables (users.access_tier integer + user_tiers string) retained by design (logic+UX collapse, no DB teardown). Internal-only; not user-visible. Full schema removal deferred to a separate migration lane if ever required.
- New users before runtime-autotrade-fix deploy still receive $0 balance — two affected users (qwneer8, Maver1ch69) already backfilled via SQL; fix ships with this PR.
- Fly.io deploy blocked until migration 030 (job_runs metadata JSONB) applied to production — trading-unblock MERGED PR #1065, live on main.
- crusaderbot-logo.png binary not yet in repo — WebTrader logo img references will render broken until PNG committed to webtrader/frontend/public/ by WARP🔹CMD.
- 5 positions stuck open — trading-unblock MERGED PR #1065. Will auto-close as MARKET_EXPIRED within 1 exit_watch tick (60s) after migration 030 applied and Fly.io deploy completes.
- fly CLI not installed in cloud execution environment — deploy step requires WARP🔹CMD manual execution from fly CLI machine.
- migration 027 (notifications_on) must be applied to production before deploying PR #1049 + PR #1055 code on Fly.io.
- pnl_insights.py, copy_trade.py, portfolio_chart.py still contain ━━━ — out-of-scope for crusaderbot-mvp-runtime-ux; separate cleanup lane required.
- WARP🔹CMD to verify Fly.io production deploy of PR #1049 + PR #1055 changes before activating on Fly.io.
- Keep production PAPER ONLY until explicit owner live activation decision.
- /deposit has no tier gate; intentional and non-blocking.
- check_alchemy_ws is TCP-only and does not perform a full WebSocket handshake; low-priority follow-up.
- ENABLE_LIVE_TRADING code default RESOLVED by crusaderbot-finalize MERGED PR #1075 — config.py default now False (paper-safe); fly.toml [env] still forces false; SENTINEL 96/100 sign-off complete.
- [DEFERRED] Ops auth full hardening (per-operator login, token rotation, token-out-of-URL) intentionally deferred for paper-mode beta. Mutators are timing-safe secret-gated, every flip audited with client_host breadcrumb, hardened bearer /admin/kill exists. Not an incomplete stub — documented in api/ops.py + config.py.
- [DEFERRED] Nightly sweep is logical-only (marks deposits swept for accounting). On-chain hot-pool transfer intentionally deferred behind EXECUTION_PATH_VALIDATED — no real capital moves in paper mode.
- integrations/polymarket.py _build_clob_client() is dead in the live execution path after Phase 4B but still indirectly referenced by submit_live_redemption(); cleanup deferred to WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP.
- Activation guards remain NOT SET and must not be changed without explicit owner decision.
- R13 backlog is post-MVP growth work and not required for current paper-safe runtime.
- [DEFERRED] No asyncio.timeout on polymarket.get_markets() in market_signal_scanner.py; scanner stall risk on hung HTTP call; P2, no capital impact.
- [DEFERRED] Migration 024 blast radius understated as test-user-only in forge report; SQL promotes all users; documentation drift, code is correct.
