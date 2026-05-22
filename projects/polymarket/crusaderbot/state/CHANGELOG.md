<!-- gate-notify-verify-v3 -->
2026-05-22 12:30 Asia/Jakarta | WARP/warp65-telegram-ux-fix | WARP-65 (issue #1278): main_menu_kb() → ReplyKeyboardMarkup (auto_on/paused/open_count); send_or_edit routes ReplyKeyboard via reply_text; dashboard STATUS_STOPPED + PRESET_CONFIG strategy label + open_count; do_start() sends launch keyboard. 1613 passed.
2026-05-22 11:30 Asia/Jakarta | WARP/warp64-ci-fix | WARP-64 (issue #1277): fix 4 CI failures in test_warp59_copy_wallet_bridge.py — wrong patch target (_send → copy_wallet namespace), missing effective_message on mock update, bridge e2e queue undercount. 1613 passed, 0 failed. CI unblocked for SENTINEL re-audit.
2026-05-22 Asia/Jakarta | WARP/warp62-63-fix | WARP-62 (issue #1273) + WARP-63 (issue #1274): threading removed from registry.py (eager module-level init); domain/signal/copy_trade.py migrated from copy_targets to copy_trade_tasks. Closes SENTINEL F-001 + F-002.
2026-05-21 22:45 | WARP/webtrader-confluence-scalper | WARP-61 (issue #1269) post-review: WARP🔹CMD Option B applied on PR #1270 — Polymarket Gamma payloads do not expose a usable 5m/15m timeframe discriminator (no duration field; endDate−startDate buckets inconsistent; slug conventions not reliable), so the runtime claim was removed from UI copy (`5m/15m` stripped from AutoTradePage strategy signal text) and the lane is explicitly documented as crypto-only eligibility + UI metadata, NOT duration-gated runtime. Forge report §5 + Not-in-Scope updated; PROJECT_STATE updated. No runtime code change; eligibility gate (category=Crypto + asset whitelist) remains intact.
2026-05-21 22:10 | WARP/webtrader-confluence-scalper | WARP-61 (issue #1269): expose `confluence_scalper` strategy in WebTrader Auto Trade UI as "Crypto Scalper" preset + Full Auto coverage with crypto-only eligibility gate (BTC/ETH/SOL/XRP/DOGE/BNB/HYPE). webtrader/frontend/src/pages/AutoTradePage.tsx STRATEGY_PRESETS card inserted between ensemble and full_auto; bot/presets.py PRESET_CONFIG + PRESET_ORDER carry the new entry; webtrader/backend/router.py _PRESET_PARAMS accepts `confluence_scalper` (risk=balanced, TP 8%, SL 4%). services/signal_scan/signal_scan_job.py: domain ConfluenceScalperStrategy now executed by run_once when active_preset permits ("confluence_scalper" preset only, or "full_auto"); _is_crypto_eligible_for_confluence() filters Gamma markets by category=Crypto + asset whitelist regex with word boundaries (BTC/ETH/SOL/XRP/DOGE/BNB/HYPE plus full names) so non-crypto markets silently skip. _STRAT_LABELS in notifications.py + notifier.py carry the new "🚀 Crypto Scalper" badge. 22 new hermetic tests (`tests/test_webtrader_confluence_scalper_exposure.py`) cover catalog exposure, selection mapping, Full Auto inclusion, preset isolation, regression on existing presets, eligibility gate (crypto + asset whitelist + word boundaries), invalid-input safety. py_compile clean on 5 touched Python files; standalone regex check PASSED 20/20. Pytest not exercised in container (telegram/cryptography Rust binding chain unsatisfiable — same posture as WARP-58/-59/-60). No schema change. STANDARD, NARROW INTEGRATION.
2026-05-21 19:30 | WARP/confluence-scalper-strategy | WARP-60 (issue #1267): optional `ConfluenceScalperStrategy` added to `projects/polymarket/crusaderbot/domain/strategy/strategies/confluence_scalper.py` and registered via `domain/strategy/registry.py:bootstrap_default_strategies` alongside existing trio (copy_trade, momentum_reversal, signal_following) without changing their behavior. Foundation-only: scan() emits SignalCandidates when all four confluence signals align (mid-band YES price 0.30–0.70, drift magnitude 0.02–0.08, liquidity ≥ max(user_filter, 5_000), 24h volume ≥ 2_000); side from drift direction (dip→YES, pop→NO); confidence is weighted sum of drift/liquidity/volume/midband sub-scores; evaluate_exit returns hold; default_tp_sl=(0.08, 0.04); risk_profile_compatibility=balanced/aggressive/custom (conservative excluded). Exported from `domain/strategy/strategies/__init__.py`. 36 new hermetic tests (`tests/test_confluence_scalper.py`). py_compile clean on 4 touched files. No execution / risk / Telegram / guard touch. No schema change. STANDARD, NARROW INTEGRATION.
2026-05-21 18:25 | WARP/warp59-copy-wallet-e2e-bridge | WARP-59 (issue #1265): MVP copy-wallet write path realigned from `copy_targets` to canonical `copy_trade_tasks` so wallets added via Telegram MVP UX flow end-to-end through `services/copy_trade/monitor.py:80` → `domain/copy_trade/repository.list_active_tasks`. bot/handlers/mvp/copy_wallet.py SELECT/INSERT/UPDATE swapped, manual upsert on (user_id, wallet_address), `copy_mode='fixed' + copy_amount=allocation_usdc` mapping for MVP $25/$50/$100/$250/Custom buckets, `do_pause` uses canonical `status='paused'`. 6 new hermetic tests (`tests/test_warp59_copy_wallet_bridge.py`). Closes WARP-57 SENTINEL MEDIUM-4. py_compile clean. No schema change. STANDARD, FUNCTIONAL.
2026-05-21 14:23 | WARP/warp56-sentry-p0-fix | WARP-56 (issue #1257): 3 Sentry P0/P1 fixes — services/signal_scan/signal_scan_job.py `_coerce_jsonb` narrowed so JSON scalar/wrong-shape values return fallback instead of leaking to `strategy.initialize()` (was ValueError: dictionary update sequence element); domain/risk/gate.py `_log` catches asyncpg.ForeignKeyViolationError at DEBUG so /admin/dry-run with synthetic user_id stops paging Sentry on every tick; migrations/001_init.sql drops `access_tier SMALLINT` from users CREATE TABLE (fresh-install DDL only — live DB already dropped via mig 044); historical access_tier comments rewritten in migs 024/031/045. 15 new + 77 existing hermetic tests pass. No schema change. STANDARD, NARROW INTEGRATION.

## [WARP-65] Telegram UX: persistent ReplyKeyboard — MERGED 184753c4b376
**Date:** 2026-05-22
**PR:** #1280 | **Branch:** WARP/warp65-telegram-ux-fix | **Tier:** STANDARD

main_menu_kb() → ReplyKeyboardMarkup (persistent, resize_keyboard, is_persistent).
State-driven labels: ⏸️ Resume / 🤖 Auto Mode / 🤖 Setup Auto, 💼 Trades(N).
_send.py: ReplyKeyboard routed via reply_text. dashboard.py: STATUS_STOPPED for
configured-not-running; PRESET_CONFIG human label; open_count wired.
autotrade.py: persistent keyboard sent after bot activation. Closes #1278.


## [WARP-64] CI pytest fix — MERGED 34f5a833b3b9
**Date:** 2026-05-22
**PR:** #1279 | **Branch:** WARP/warp64-ci-fix | **Tier:** STANDARD

Test-only fix. Fixes 4 CI failures in test_warp59_copy_wallet_bridge.py:
patch use-site (copy_wallet.send_or_edit), missing effective_message, queue undercount.
Result: 1613 passed, 0 failed. Closes #1277.


## [WARP-62+63] SENTINEL fix cycle — MERGED 5f84646e1d9c
**Date:** 2026-05-22
**PR:** #1275 | **Branch:** WARP/warp62-63-fix | **Tier:** STANDARD

WARP-62: `domain/strategy/registry.py` — `import threading` removed. Eager module-level `_DEFAULT_REGISTRY = StrategyRegistry()`. H2 HARD RULE cleared.
WARP-63: `domain/signal/copy_trade.py` — `CopyTradeStrategy.scan()` reads `copy_trade_tasks` (canonical). `copy_targets` removed. F-002 architectural drift cleared.
9 hermetic tests. Closes #1273 + #1274.


## [SENTINEL] CrusaderBot Core Audit 2026-05-21 — BLOCKED ac1c207f2238
**Date:** 2026-05-22
**PR:** #1272 | **Branch:** WARP/sentinel-core-audit-2026-05-21 | **Score:** 60/100

Verdict: BLOCKED — H2 threading.Lock violation in registry.py (F-001 P0).
7/8 subsystems PASS. Risk gate, execution router, kill switch, WebTrader, Telegram, confluence scalper, DB migrations all clean.
Fix cycle open: WARP-62 (P0 threading) + WARP-63 (P1 copy_targets drift).


## [WARP-61] WebTrader + Full Auto confluence_scalper exposure — MERGED 7cbd8b814533
**Date:** 2026-05-21
**PR:** #1270 | **Branch:** WARP/webtrader-confluence-scalper | **Tier:** STANDARD

WebTrader AutoTradePage: Crypto Scalper preset card (engine=ConfluenceScalperStrategy, advanced risk, high freq).
signal_scan_job Phase B: confluence_scalper runs after lib loop, preset-gated, exception-safe.
eligibility.py: crypto-only whitelist BTC/ETH/SOL/XRP/DOGE/BNB/HYPE — word-boundary regex.
Full Auto + no-preset users covered. Existing presets isolated. 22 new hermetic tests.


## [WARP-60] ConfluenceScalperStrategy — MERGED b3ec4b7d4930
**Date:** 2026-05-21
**PR:** #1268 | **Branch:** WARP/confluence-scalper-strategy | **Tier:** STANDARD

New optional strategy: multi-signal alignment scalper for mid-band Polymarket markets.
Confluence: YES price 0.30–0.70 + drift 2–8% + liquidity $5k+ + volume 24h $2k+.
Side: mean-reversion (drift<0→YES, drift>0→NO). TP 8% / SL 4%.
Registered via bootstrap_default_strategies() — idempotent. No preset activation wired.
36 hermetic tests.


## [WARP-59] Copy Wallet e2e bridge — MERGED 68a523e94cd8
**Date:** 2026-05-21
**PR:** #1266 | **Branch:** WARP/warp59-copy-wallet-e2e-bridge | **Tier:** STANDARD

Option B: `bot/handlers/mvp/copy_wallet.py` writes/reads `copy_trade_tasks` (canonical execution table).
Manual upsert on re-add. `copy_mode='fixed'`, `copy_amount=allocation_usdc`.
Production scanner (`services/copy_trade/monitor.py`) now picks up MVP-added wallets.
Closes WARP-57 SENTINEL MEDIUM-4.


## [WARP-58] Fix domain/signal/copy_trade.py schema — MERGED 4501fa8befb2
**Date:** 2026-05-21
**PR:** #1264 | **Branch:** WARP/warp58-copy-trade-schema-fix | **Tier:** STANDARD

Fixed CopyTradeStrategy.scan() column refs to match 009_copy_trade.sql:
- `wallet_address` → `target_wallet_address`
- `enabled=TRUE` → `status='active'`
Copy-wallet domain scan engine restored.


## [WARP-57] Telegram UX MVP v1 Rebuild — MERGED c6ae44b18572
**Date:** 2026-05-21
**PR:** #1261 | **Branch:** WARP/warp57-telegram-ux-mvp | **Tier:** MAJOR
**SENTINEL:** CONDITIONAL APPROVED 92/100 (issue #1262)

Additive Telegram UX MVP v1 layer:
- `bot/ui/tree.py` — hierarchy tree helpers + status glyphs
- `bot/messages_mvp.py` — pure screen renderers (all 6 surfaces)
- `bot/handlers/mvp/` — 8 handler modules (dashboard/autotrade/copy_wallet/portfolio/markets/settings/help/onboarding)
- `bot/keyboards/mvp/` — 8 keyboard modules (InlineKeyboardMarkup only)
- `bot/dispatcher.py` — MVP attach() first, all 7 callback prefixes registered

Hard product rules enforced: no manual trade buttons, markets intelligence-only, activation guards untouched.

**Follow-up: WARP-58** — fix `domain/signal/copy_trade.py:23` schema (`enabled` → `status='active'`, `wallet_address` → `target_wallet_address`).


2026-05-21 13:24 | WARP/warp54-closed-beta-hardening | WARP-54 (issue #1253): closed-beta P1 hardening — notifications.send falls back to plain text on BadRequest from parse_mode=HTML (BadRequest also excluded from retry predicate since it's non-transient but inherits from NetworkError in PTB v22, was burning the attempt budget); /admin HUD adds stuck-position row counting (close_failure_count > 0) OR (opened_at < NOW() - INTERVAL '24 hours'); scheduler one-shot startup_recovery_log job logs "Resumed monitoring N open positions" on every boot for restart-recovery audit trail. Audit-pinned (no code change): paper.execute idempotency_key ON CONFLICT dedup, paper.close_position WHERE user_id=$5 scoping, exit_watcher 3-tick threshold for API timeout. 6 new + 48 existing hermetic tests pass. No schema change. STANDARD, NARROW INTEGRATION.

2026-05-21 12:57 | WARP/warp53-reliability-hardening | WARP-53 (issue #1252): Telegram delivery + paper-close P0 hardening — notifications.send wait strategy now honours RetryAfter.retry_after (capped 30s) instead of fixed exponential, max attempts 3→4; per-event "no silent swallow" WARNING added at notifier._send, _edit_or_resend, _send_safe, and all 7 alert_user_* (refactored through new _send_user_exit_alert helper); paper.close_position double-close idempotency pinned by new regression test (already_closed branch fires zero extra ledger/audit/snapshot writes). 7 new + 28 existing hermetic tests pass. No schema change, no code change to paper engine. STANDARD, NARROW INTEGRATION.

2026-05-21 11:49 | WARP/portfolio-snapshots-writer | WARP-52 (issue #1245): portfolio_snapshots Python writer wired — new services/portfolio_snapshots.py (write_snapshot + snapshot_active_users); paper.close_position calls write_snapshot inline after txn commit (domain/execution/paper.py:139); scheduler portfolio_snapshots tick at PORTFOLIO_SNAPSHOT_INTERVAL=60s registered alongside exit_watch; cb_portfolio NOTIFY channel now live via mig 029 AFTER INSERT trigger; 7 hermetic regression tests pass + 31 exit_watcher tests pass (no regression). No schema change. STANDARD, NARROW INTEGRATION.

2026-05-21 11:06 | WARP/runtime-spine-validation | WARP-46 (issue #1243): runtime spine evidence pass — 7 #1243 targets verified REAL against current main HEAD (start/scan→trade/positions/close/receipt/PnL/routing); NOTIFY triggers cb_orders/cb_fills/cb_positions confirmed wired (mig 029); job_runs.metadata writer verified (scheduler.py:482 + job_tracker.py:85, mig 030); silent-exception audit clean; portfolio_snapshots Python writer GAP surfaced as advisory (cb_portfolio NOTIFY channel dormant — out of #1243 scope). No code modified. STANDARD, NARROW INTEGRATION.

2026-05-21 08:30 | MERGED #1224 WARP/warp51-drop-access-tier | WARP-51 (issue #1220): full Python access_tier cleanup — INSERT/SELECT stripped from users.py, user_service.py, seed_demo_data.py; set_tier/force_set_tier deleted; /allowlist → set_role('admin'); seed_operator_tier.py deleted + fly.toml release_command removed; migration 044_drop_access_tier.sql re-enabled (IF EXISTS); 16 test fixtures swept; 1487 pytest passed. MAJOR, NARROW INTEGRATION. SENTINEL APPROVED 99/100 (issue #1225). SHA 1b9c3fdb5e6c.

2026-05-21 08:08 | WARP/warp51-drop-access-tier | WARP-51 (issue #1220): every Python access_tier writer/reader removed; `set_tier`/`force_set_tier` deleted; `/allowlist` converted to `set_role('admin')`; `scripts/seed_operator_tier.py` deleted + `fly.toml [deploy].release_command` removed; migration `044_drop_access_tier.sql` re-enabled; 16 test files fixture-swept; 1487 pytest passed. MAJOR, NARROW INTEGRATION. SENTINEL pending.

## [WARP-55] — 2026-05-21

- **proof:** `RUNTIME_EVIDENCE.md` — all 7 P2 finish criteria verified against live Supabase (275 signal_scan, 1491 exit_watch, 104 portfolio_snapshots runs; 25 stable paper positions, 0 stuck, 0 user bleed)
- **🏁 CrusaderBot closed beta DONE.** Activation guards LOCKED pending owner decision.
- Merged PR #1259 (SHA abd3b43dbe10) — STANDARD, evidence-only
## [WARP-56] — 2026-05-21

- **fix:** `_coerce_jsonb` in `signal_scan_job.py` now narrows return type to match `fallback` shape — JSON scalar `strategy_params` (e.g. `"balanced"`) no longer leaks into `strategy.initialize()` and triggers `ValueError` (Sentry 9x, scanner dead)
- **fix:** `domain/risk/gate._log` catches `ForeignKeyViolationError` at DEBUG — `/admin/dry-run` with synthetic user_id no longer floods Sentry with FK errors (Sentry 2x)
- **fix:** `migrations/001_init.sql` CREATE TABLE `users` — `access_tier SMALLINT` column removed; comments in 024/031/045 cleaned; fresh DB install can no longer recreate the ghost column
- Merged PR #1258 (SHA c98efc5765d9) — STANDARD, NARROW INTEGRATION
## [2026-05-21 06:32] WARP-54 MERGED (70d3beff7257) — Closed Beta P1 Hardening
- `notifications.py`: BadRequest plain-text fallback — no silent HTML parse drop
- `scheduler.py`: `startup_recovery` job logs resumed monitoring count on restart
- `admin.py`: /admin HUD surfaces stuck open positions
- 6 regression tests pin dedup, user_id scoping, exception-swallow behaviours
- All 6 P1 WORKTODO items closed
- Closes Issue #1253

## [2026-05-21 06:06] WARP-53 MERGED (96d397ee234b) — Telegram delivery hardening + paper-close idempotency
- `notifications.py`: `_wait_telegram()` honours Telegram 429 RetryAfter (capped 30s), attempts 3→4
- `notifier.py` + `notification_service.py`: per-event WARNING on every silent notification drop
- `monitoring/alerts.py`: `_send_user_exit_alert` helper + WARNING on drop
- `paper.close_position`: double-close idempotency guard
- 7 regression tests pass; CI clean
- Closes Issue #1252

## 2026-05-21 — Migrations 027/029/030/031/044 Applied to Supabase Production

- **027** `notifications_on` column added to `user_settings` (BOOLEAN DEFAULT TRUE)
- **029** `portfolio_snapshots` + `system_alerts` tables created; LISTEN/NOTIFY triggers wired
- **030** `metadata JSONB` column added to `job_runs`
- **031** Signal scanner user enrollment: demo/live feeds seeded, users enrolled in `signal_following`, subscribed to demo feed
- **044** `access_tier` column DROPPED from `users` — role-based model (`admin`/`user`) fully active
- All migrations executed via Supabase Management API by WARP🔹CMD [warp-gate[bot]]

## [2026-05-21] WARP-46 — Runtime Spine Validation MERGED (PR #1244)

- 7/7 validation targets REAL (start / scan→trade / positions / close / receipt / PnL / routing)
- NOTIFY triggers cb_orders/cb_fills/cb_positions confirmed wired (migration 029)
- job_runs.metadata populated each tick confirmed (scheduler.py:482-529)
- Zero silent-exception swallowing in production paths
- Advisory: portfolio_snapshots has no Python writer — cb_portfolio channel dormant (out-of-scope, tracked)
- Merge SHA: 54e32a006f4b — STANDARD tier, no SENTINEL required
- Gate: MERGE ✅
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

2026-05-21 18:00 | WARP/warp57-telegram-ux-mvp | WARP-57 (#1260): Telegram UX MVP v1 rebuild — full IA + hierarchy-tree terminal UX (Dashboard / Auto Trade / Copy Wallet / Portfolio / Markets / Settings / Help). New layer: bot/ui/tree.py, bot/messages_mvp.py, bot/keyboards/mvp/*, bot/handlers/mvp/*. Dispatcher rewired for auto:/copy:/portfolio:/markets:/settings:/help: callback prefixes + menu:* routing; persistent reply-kb taps route to MVP. No manual trade buttons, no live-mode bypass, paper default unchanged. Domain/services/migrations untouched. MAJOR, FOUNDATION (UX-only).

2026-05-21 19:30 | WARP/warp57-telegram-ux-mvp | WARP-57 SENTINEL (#1262): audit complete — BLOCKED. Score 78/100, 1 critical (copy_targets schema mismatch — bot/handlers/mvp/copy_wallet.py SQL references `target_address`/`allocation_usdc` columns absent from canonical mig 009 schema; silent persistence failure under defensive try/except). 3 MEDIUMs (wallets.public_address→deposit_address; auto:start no engine bootstrap; legacy /settings sub-routes fall through to MVP home). Activation guards / no-manual-trade / paper-default checks all PASS. Report: reports/sentinel/warp57-telegram-ux-mvp.md.

2026-05-21 20:15 | WARP/warp57-telegram-ux-mvp | WARP-57 SENTINEL re-audit (#1262): verdict APPROVED at SHA aa4fe24c. Score 86/100, 0 critical. Round-1 CRITICAL-1 (copy_targets column mismatch) + MEDIUM-1 (wallets.public_address) both verified RESOLVED by forge fixes 4473482+aa4fe24. New MEDIUM-4 logged for post-merge follow-up: MVP writes to `copy_targets` but production scanner reads `copy_trade_tasks` — table swap needed in a follow-up lane to wire end-to-end mirror. MEDIUM-2/3 remain P2 per prior WARP🔹CMD direction.

2026-05-21 16:16 | WARP/warp58-copy-trade-schema-fix | WARP-58 (#1263): domain/signal/copy_trade.py `copy_targets` SELECT migrated to canonical mig 009 schema — `wallet_address` → `target_wallet_address`, `enabled=TRUE` → `status='active'`; three downstream dict reads (Polymarket Data API call, warning log, `SignalCandidate.extra["target"]`) re-keyed to `target_wallet_address`. Legacy `UPDATE copy_targets SET last_seen_tx=$1 WHERE id=$2` preserved (column retained by 009, keyed on PK `id`). Closes WARP-57 SENTINEL Round-1 read-path drift in domain scanner that `scheduler.py:26` imports as `CopyTradeStrategy`. py_compile clean on touched file + scheduler.py consumer chain; pytest not available in container. No schema change. STANDARD, NARROW INTEGRATION.
