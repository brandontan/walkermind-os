2026-05-21 08:30 | MERGED #1224 WARP/warp51-drop-access-tier | WARP-51 (issue #1220): full Python access_tier cleanup — INSERT/SELECT stripped from users.py, user_service.py, seed_demo_data.py; set_tier/force_set_tier deleted; /allowlist → set_role('admin'); seed_operator_tier.py deleted + fly.toml release_command removed; migration 044_drop_access_tier.sql re-enabled (IF EXISTS); 16 test fixtures swept; 1487 pytest passed. MAJOR, NARROW INTEGRATION. SENTINEL APPROVED 99/100 (issue #1225). SHA 1b9c3fdb5e6c.

2026-05-21 08:08 | WARP/warp51-drop-access-tier | WARP-51 (issue #1220): every Python access_tier writer/reader removed; `set_tier`/`force_set_tier` deleted; `/allowlist` converted to `set_role('admin')`; `scripts/seed_operator_tier.py` deleted + `fly.toml [deploy].release_command` removed; migration `044_drop_access_tier.sql` re-enabled; 16 test files fixture-swept; 1487 pytest passed. MAJOR, NARROW INTEGRATION. SENTINEL pending.

## 2026-05-21 — Migrations 027/029/030/031/044 Applied to Supabase Production

- **027** `notifications_on` column added to `user_settings` (BOOLEAN DEFAULT TRUE)
- **029** `portfolio_snapshots` + `system_alerts` tables created; LISTEN/NOTIFY triggers wired
- **030** `metadata JSONB` column added to `job_runs`
- **031** Signal scanner user enrollment: demo/live feeds seeded, users enrolled in `signal_following`, subscribed to demo feed
- **044** `access_tier` column DROPPED from `users` — role-based model (`admin`/`user`) fully active
- All migrations executed via Supabase Management API by WARP🔹CMD [warp-gate[bot]]

## [2026-05-21] WARP-GATE — Migrations 027/029/030/031/044 Applied

- **027** `user_settings.notifications_on BOOLEAN DEFAULT TRUE` — added
- **029** `portfolio_snapshots` + `system_alerts` tables created; NOTIFY triggers wired (orders/fills/positions/user_settings)
- **030** `job_runs.metadata JSONB` — added
- **031** Demo + Live signal feeds seeded; 6 users enrolled in `signal_following` strategy; demo feed subscriptions created
- **044** `access_tier` column DROP confirmed — column absent from `users` schema; `role` column present
- Executed via WARP🔹CMD direct Supabase Management API (PAT) — no manual SQL Editor required
## [2026-05-21] WARP-50b — role-based access model (PR #1222)
## [2026-05-21] Hotfix — disable migration 044 (PR #1223)

- Renamed `044_drop_access_tier.sql` → `044_drop_access_tier.sql.disabled`
- Prevents crash loop: `run_migrations()` glob skips `.disabled` files
- `access_tier` column now safe to keep as placeholder on Fly restarts
- SHA d7164775491e



- Merged `WARP/fix-access-tier-open-warp50b` → main (SHA aa17b2a7135a)
- Replaced all `access_tier` integer gating with `users.role` ('admin'|'user') across 16 production files
- Added migration `045_add_role_column.sql` (idempotent, admin bootstrap)
- `access_tier` column kept for backward compat; DROP staged behind `044_drop_access_tier.sql`
- pytest: 1512 passed, 0 failed
- Closes Issue #1219


2026-05-20 23:24 | WARP/fix-drop-access-tier-warp50 | WARP-50 MERGED (67f072a0): 044_drop_access_tier.sql created (NOT applied); Python audit found 16 prod files still reference access_tier; WARP-50b (#1219) dispatched for open-access fix; WARP-51 (#1220) backlogged for full role-based migration. MINOR, audit artifact.
2026-05-20 23:10 | WARP/fix-migrations-warp49 | WARP-49 MERGED (b7e1fe14): 031 Step 5 access_tier UPDATE removed (role-based scope); 027/029/030 confirmed clean. Migrations 027-031 ready for Supabase execution. MINOR, NARROW INTEGRATION
2026-05-20 22:50 | WARP-48 MERGED (92fb5e33): fly.toml ADMIN_API_TOKEN placeholder; signal_scan_job silent except→log.warning; paper.py trade open/close structlog; vite build 0 errors; migrations 027/029/030/031 audited NOT APPLIED. STANDARD, NARROW INTEGRATION
2026-05-20 16:41 | WARP/fix-webtrader-realtime-warp47 | WARP-47 MERGED (766b9864): GET /activity endpoint added (last N trade events per user); D1 terminal auto-refresh confirmed; D2 scanner_tick→TopBar confirmed; D3 activity endpoint fixed; D4 portfolio_update SSE confirmed; D5 PAPER posture confirmed. STANDARD, NARROW INTEGRATION
2026-05-20 16:10 | WARP/fix-runtime-spine-warp46 | WARP-46: runtime spine evidence matrix — all 12 steps REAL, 2 DEAD strategies (MomentumReversal, SignalFollowing), 15-gate risk evaluation confirmed, all 4 paper-safety guards default False. STANDARD, MODERATE
2026-05-20 15:30 | WARP/fix-active-issues | WARP-35+WARP-37: Linear status sync — both issues closed to Done; fixes confirmed in main (7f14c42d, 088bad4, 843bb6c); no code changes in this lane. MINOR, FOUNDATION
2026-05-20 14:52 | WARP/feat-pagination-warp19 | WARP-19 MERGED (2fc2929d): Load More pagination audit — all 4 surfaces confirmed (Market Feed, Leaderboard, Closed Trades, Orders); ScannerContext + TopBar last_scan display wired; vite build clean. STANDARD, NARROW INTEGRATION
2026-05-20 14:04 | WARP/fix-webtrader-sse-warp21 | WARP-21 MERGED (97e7d25a): Pre-audit 5/6 deliverables present; gap patched (scanner.tick→TopBar display via ScannerContext + useScannerStatus hook). STANDARD, NARROW INTEGRATION
2026-05-20 13:20 | WARP/fix-sentry-p1-runtime-bugs | WARP-45: _coerce_jsonb() added to signal_scan_job.py; asyncpg JSONB-as-str ValueError fixed (Sentry DAWN-SNOWFLAKE-1729-1Q); STANDARD, NARROW INTEGRATION
2026-05-20 10:46 | WARP/fix-dashboard-portfolio-routing | WARP-43: dashboard:portfolio callback split from trades branch — now routes to show_portfolio; dashboard:trades retained; MINOR, NARROW INTEGRATION
2026-05-20 14:00 | WARP/tg-ux-blueprint-v7 | WARP-41+WARP-42: Dashboard inline KB removed; Close buttons labelled per-position; Settings hub TP/SL entry; Help Home button; Trades(N) → show_positions routing; STANDARD, BROAD INTEGRATION
2026-05-20 07:07 | WARP/fix-full-system-audit | WARP-40 (issue #1186): full system audit — BUG-1+BUG-4 dynamic `💼 Trades (N)` routed at group=-1 + dead `📈 My Trades` handler removed; BUG-2 `🤖 Auto Mode` shows preset_active when active preset; BUG-3 ghost inline-kb cleared on dashboard render; BUG-5 `_unrealized_pnl` strict-interior guard (0<cp<1) for stale CLOB-sentinel DB rows; STANDARD, NARROW INTEGRATION
2026-05-19 23:49 | WARP/fix-date-str-query-arg | WARP-35: regression tests for _get_daily_spend + _record_spend — asserts datetime.date not str passed to asyncpg; production fix already in #1170; STANDARD, NARROW INTEGRATION
2026-05-19 23:49 | WARP/fix-tg-edit-not-modified | WARP-37: BadRequest "not modified" guard added to 6 inline-edit handlers (setup.py x5, settings.py x1); bare except BadRequest replaced with targeted not-modified check + re-raise; MINOR, NARROW INTEGRATION
2026-05-19 23:45 | WARP/fix-leaderboard-numeric-overflow | WARP-36: math.isfinite() guard added to _safe_float; _clamp helper replaces manual max/min blocks; NaN no longer bypasses NUMERIC schema bounds in leaderboard_sync.py; STANDARD, NARROW INTEGRATION
2026-05-19 20:20 | WARP/public-readiness-gate | WARP-33 MERGED direct-apply (f6525a5c→fdc2367a): README repo-structure tree fix, KNOWLEDGE_BASE header refresh (WalkerMind OS, walkermind-os URL, WARP CMD), Phase 4 forge report added; MINOR, FOUNDATION, PAPER-ONLY
2026-05-19 19:25 | WARP-32/multi-user-isolation-admin-hud | WARP-32 MERGED PR #1174 (c34a4276): SQL isolation audit PASS, /admin status HUD, Migration 042 DROP TABLE sessions; STANDARD, NARROW INTEGRATION
2026-05-19 19:05 | WARP/phase-2-power-mode-ux | WARP-31 MERGED PR #1173 (8563d6b1): 8-step concierge onboarding wizard, dynamic state-aware main menu (paused/open_count labels), 32-char DIV standardization across all Telegram screens; STANDARD, NARROW INTEGRATION
2026-05-19 18:00 | WARP/phase1-hardening-db-cleanup | WARP-30: signal freshness gate tests (4 cases added), SSE reliability audit PASS, migrations 030/031/041 applied to Supabase production; STANDARD, NARROW INTEGRATION
2026-05-19 14:30 | WARP/sentry-burn-readiness | WARP-29: Sentry fixes verified on main; Signal Freshness Gate verified on main; Telegram Power Mode keyboards — [ 📈 View Position ] [ 🛑 Close Position ] [ ⏸️ Pause Copy ] in notification_service.py + notifier.py; paper.py position_id wired; STANDARD, NARROW INTEGRATION
2026-05-19 11:15 | WARP/master-cleanup-v5-beta-rebase | WARP-26 MERGED PR #1169: copy trade engine sync + reasoning injection + rm_mirror fix + CI test alignment; CodeRabbit fixes applied; CI + SonarQube green; WARP🔹CMD merged directly
2026-05-19 | WARP/CRUSADERBOT-SENTRY-FIXES | fix date.isoformat→date object in monitor.py (DataError); job_runs metadata $6::jsonb cast; migration 032 user_id guard; preset_picker_kb→preset_picker alias; STANDARD, NARROW INTEGRATION
2026-05-19 10:30 | WARP/master-cleanup-v5-beta | WARP-26 follow-up: test_copy_trade.py + test_signal_following.py aligned to new schema; rm_mirror sizing regression fixed (mirror_size_direct); unknown mode guard added
2026-05-19 09:21 | WARP/master-cleanup-v5-beta | WARP-26: copy_trade.py reads copy_trade_tasks + copy_trade_idempotency dedup; SignalCandidate.reasoning added; all 3 strategies injected; messages.py 32-char dividers; MAJOR, FULL RUNTIME INTEGRATION
2026-05-19 08:55 | WARP-28/dashboard-corruption-fix | EMERGENCY: restored 3 Base64-corrupted Python files + DIV 26→32 in messages.py; compileall clean; deployment blocker resolved
2026-05-18 23:45 | WARP/telegram-functional-routing-fix | WARP-25: show_positions() callback fix + Positions Close buttons + Trades history-only nav + preset label shortening; STANDARD, FULL RUNTIME INTEGRATION
2026-05-18 23:30 | WARP/expand-webtrader-pagination | WARP-19: Load More pagination (offset-based) for Live Market Feed, Leaderboard, Closed Trades, Orders; api.ts offset param added; STANDARD, FULL RUNTIME INTEGRATION
2026-05-18 21:00 | WARP/truth-integration-mock-cleanup | WARP-21: Live Market Feed 30s poll→SSE, scanner.tick ts payload, Discover case-insensitive category + SSE refresh, mock audit clean; STANDARD, FULL RUNTIME INTEGRATION
2026-05-19 | WARP/CRUSADERBOT-UI-COLLAPSIBLE-FIX | all CollapsibleSection defaultOpen=true; SHOW/HIDE labeled toggle button; pagination scoped to ledger + market list only; STANDARD, NARROW INTEGRATION
2026-05-19 | WARP/CRUSADERBOT-UI-FEED-CASHOUT | Dashboard Recent Activity replaced with Live Market Feed (signal_publications, 30s refresh); Cash Out button green=profit / red=loss; STANDARD, NARROW INTEGRATION
2026-05-19 | WARP/CRUSADERBOT-SPA-AUTH-FIX | SPAStaticFiles 404→index.html fallback; navigate("/") post-login redirect; upsert_user replaces 403 gate — webtrader login works without prior /start; STANDARD, NARROW
2026-05-19 | WARP/CRUSADERBOT-MARKET-SYNC-FIX | market_sync 1800s→300s; paper fill now uses get_live_market_price() matching exit_watcher source — eliminates entry/exit price gap that caused instant TP; live_price_override is-not-None guard (handles price=0.0); STANDARD, NARROW INTEGRATION
2026-05-19 09:00 | WARP/webtrader-wallet-qr-activity-pagination | Deposit+QR modal, Withdraw modal, CollapsibleSection (5 pages), ledger Load More pagination + dedup, /wallet/ledger endpoint, paper_mode in WalletInfo; stable ledger IDs; Vite build clean; STANDARD, NARROW INTEGRATION
2026-05-20 02:10 | WARP/fix-pnl-current-price | WARP-38 (#1182): get_live_market_price strict-interior guard (0<p<1) on CLOB primary + Gamma fallback — rejects CLOB empty-book 1.0/0.0 sentinel that marked open longshot positions at $1.00 (+900% P&L); invalid lookup → None → entry_price mark; 4 regression tests; STANDARD, NARROW INTEGRATION

2026-05-20 19:00 | WARP/strategy-pipeline-user-filter | WARP-44 (#1195): per-user category_filters market filter + strategy_params wire-up; migration 043 (strategy_params JSONB); _filter_markets_by_category helper; run_once Phase A+B merged per-user; 9 unit tests; STANDARD, MODERATE
