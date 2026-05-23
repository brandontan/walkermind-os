<!-- gate-notify-verify-v3 -->
## [SENTINEL-AUDIT] F-CRIT-1 fix — bot/ui/__init__.py realigned — MERGED fa1bd2537650
**Date:** 2026-05-23 | **PR:** #1294 | **Tier:** STANDARD

SENTINEL system audit (pre-handoff): BLOCKED 62/100 → F-CRIT-1 resolved.
bot/ui/__init__.py: BAR/BRANCH/LAST removed (no longer exported by tree.py since WARP-67/71/73).
App boots clean from main. 1613 tests pass, 0 collection errors.
F-HIGH-2 (zero live trade data) deferred — separate lane.
Fly.io redeploy required.

## [WARP-73] Phantom dot + clean HTML format hotfix
**Date:** 2026-05-23 | **Tier:** MINOR (hotfix, direct to main)

1. onboarding.py: remove reply_text(".") from /start returning user path
2. tree.py: safe unicode divider ─×28, · separator — no ━━ or box chars
3. messages_mvp.py: full rewrite — all 66 functions clean Telegram HTML

## [WARP-72] Fix phantom dot + capital from _read_state — 93d5709c0c5c
**Date:** 2026-05-23
**Commit:** 93d5709c0c5c | **Tier:** MINOR (hotfix, direct to main)

1. Remove `reply_text(".")` phantom dot — use `send_or_edit` with `main_menu_kb` instead.
2. `do_start()` now calls `_read_state(user)` to get real capital (balance x risk fraction)
   instead of `_flow(ctx)["capital"]` which was always `_DEFAULT_CAPITAL=100.0`.

## [WARP-71] Premium terminal UI — HTML parse mode — MERGED e443c212c1e7
**Date:** 2026-05-23
**PR:** #1293 | **Tier:** STANDARD

tree.py HTML helpers: html\_escape, pre\_block, leaf/section/nested/cta/title.
DIV=━×32. \_send.py parse\_mode=HTML. All 66 render functions updated.
Bloomberg-lite terminal: \<pre\> blocks for numbers, \<b\> headers, \<code\> values.

## [WARP-70] Dynamic capital from risk profile — MERGED eb149d18427b
**Date:** 2026-05-23
**PR:** #1292 | **Tier:** MINOR

Capital = balance × risk fraction (safe 25%, balanced 50%, aggressive 80%).
Fallback $100 when balance = 0.

## [WARP-69] Full structured card format — MERGED b50ef1a2ce86
**Date:** 2026-05-23
**PR:** #1289 | **Branch:** WARP/warp69-full-card-format | **Tier:** STANDARD

All 66 render functions in messages\_mvp.py: leaf() · separator, section() indented,
nested() bullets, cta() italic, DIVIDER/CARD\_DIVIDER. Settings values shortened.
autotrade\_home DIVIDER between blocks. Help nested() topic lists.


Structured card UI: leaf() → Label·Value, section() indented, divider() ┄┄┄, CARD\_DIVIDER ━━━, cta() italic.
Dashboard: DIVIDER sections + » summary rows.
Positions: 3-per-page pagination, card per position, bold title, Prev/Next nav.


2026-05-23 02:30 Asia/Jakarta | WARP/warp69-full-card-format | WARP-69 (issue #1288): messages_mvp.py all 64 remaining render functions updated to structured card format — leaf · separator, section/nested/cta/DIVIDER/CARD_DIVIDER throughout; settings_home values shortened; dashboard_new_user restructured with divider+cta; autotrade_home DIVIDER sections; help screens use nested(); system screens use cta(); 66/66 render functions consistent. py_compile clean. STANDARD, VISUAL/UX.
2026-05-23 01:46 Asia/Jakarta | WARP/warp68-structured-card-ui | WARP-68 (issue #1286): tree.py leaf/section upgraded to · separator + DIVIDER/CARD_DIVIDER; render_dashboard_default DIVIDER sections; render_positions_list paginated cards; positions_list_kb Prev/Next; show_positions_page handler. py_compile clean. STANDARD, NARROW INTEGRATION.
2026-05-22 12:30 Asia/Jakarta | WARP/warp65-telegram-ux-fix | WARP-65 (issue #1278): main_menu_kb() → ReplyKeyboardMarkup (auto_on/paused/open_count); send_or_edit routes ReplyKeyboard via reply_text; dashboard STATUS_STOPPED + PRESET_CONFIG strategy label + open_count; do_start() sends launch keyboard. 1613 passed.
2026-05-22 11:30 Asia/Jakarta | WARP/warp64-ci-fix | WARP-64 (issue #1277): fix 4 CI failures in test_warp59_copy_wallet_bridge.py — wrong patch target (_send → copy_wallet namespace), missing effective_message on mock update, bridge e2e queue undercount. 1613 passed, 0 failed. CI unblocked for SENTINEL re-audit.
2026-05-22 Asia/Jakarta | WARP/warp62-63-fix | WARP-62 (issue #1273) + WARP-63 (issue #1274): threading removed from registry.py (eager module-level init); domain/signal/copy_trade.py migrated from copy_targets to copy_trade_tasks. Closes SENTINEL F-001 + F-002.
2026-05-21 22:45 | WARP/webtrader-confluence-scalper | WARP-61 (issue #1269) post-review: WARP🔹CMD Option B applied on PR #1270 — Polymarket Gamma payloads do not expose a usable 5m/15m timeframe discriminator (no duration field; endDate−startDate buckets inconsistent; slug conventions not reliable), so the runtime claim was removed from UI copy (`5m/15m` stripped from AutoTradePage strategy signal text) and the lane is explicitly documented as crypto-only eligibility + UI metadata, NOT duration-gated runtime. Forge report §5 + Not-in-Scope updated; PROJECT_STATE updated. No runtime code change; eligibility gate (category=Crypto + asset whitelist) remains intact.
2026-05-21 22:10 | WARP/webtrader-confluence-scalper | WARP-61 (issue #1269): expose `confluence_scalper` strategy in WebTrader Auto Trade UI as "Crypto Scalper" preset + Full Auto coverage with crypto-only eligibility gate (BTC/ETH/SOL/XRP/DOGE/BNB/HYPE). webtrader/frontend/src/pages/AutoTradePage.tsx STRATEGY_PRESETS card inserted between ensemble and full_auto; bot/presets.py PRESET_CONFIG + PRESET_ORDER carry the new entry; webtrader/backend/router.py _PRESET_PARAMS accepts `confluence_scalper` (risk=balanced, TP 8%, SL 4%). services/signal_scan/signal_scan_job.py: domain ConfluenceScalperStrategy now executed by run_once when active_preset permits ("confluence_scalper" preset only, or "full_auto"); _is_crypto_eligible_for_confluence() filters Gamma markets by category=Crypto + asset whitelist regex with word boundaries (BTC/ETH/SOL/XRP/DOGE/BNB/HYPE plus full names) so non-crypto markets silently skip. _STRAT_LABELS in notifications.py + notifier.py carry the new "🚀 Crypto Scalper" badge. 22 new hermetic tests (`tests/test_webtrader_confluence_scalper_exposure.py`) cover catalog exposure, selection mapping, Full Auto inclusion, preset isolation, regression on existing presets, eligibility gate (crypto + asset whitelist + word boundaries), invalid-input safety. py_compile clean on 5 touched Python files; standalone regex check PASSED 20/20. Pytest not exercised in container (telegram/cryptography Rust binding chain unsatisfiable — same posture as WARP-58/-59/-60). No schema change. STANDARD, NARROW INTEGRATION.
2026-05-21 19:30 | WARP/confluence-scalper-strategy | WARP-60 (issue #1267): optional `ConfluenceScalperStrategy` added to `projects/polymarket/crusaderbot/domain/strategy/strategies/confluence_scalper.py` and registered via `domain/strategy/registry.py:bootstrap_default_strategies` alongside existing trio (copy_trade, momentum_reversal, signal_following) without changing their behavior. Foundation-only: scan() emits SignalCandidates when all four confluence signals align (mid-band YES price 0.30–0.70, drift magnitude 0.02–0.08, liquidity ≥ max(user_filter, 5_000), 24h volume ≥ 2_000); side from drift direction (dip→YES, pop→NO); confidence is weighted sum of drift/liquidity/volume/midband sub-scores; evaluate_exit returns hold; default_tp_sl=(0.08, 0.04); risk_profile_compatibility=balanced/aggressive/custom (conservative excluded). Exported from `domain/strategy/strategies/__init__.py`. 36 new hermetic tests (`tests/test_confluence_scalper.py`). py_compile clean on 4 touched files. No execution / risk / Telegram / guard touch. No schema change. STANDARD, NARROW INTEGRATION.
2026-05-21 18:25 | WARP/warp59-copy-wallet-e2e-bridge | WARP-59 (issue #1265): MVP copy-wallet write path realigned from `copy_targets` to canonical `copy_trade_tasks` so wallets added via Telegram MVP UX flow end-to-end through `services/copy_trade/monitor.py:80` → `domain/copy_trade/repository.list_active_tasks`. bot/handlers/mvp/copy_wallet.py SELECT/INSERT/UPDATE swapped, manual upsert on (user_id, wallet_address), `copy_mode='fixed' + copy_amount=allocation_usdc` mapping for MVP $25/$50/$100/$250/Custom buckets, `do_pause` uses canonical `status='paused'`. 6 new hermetic tests (`tests/test_warp59_copy_wallet_bridge.py`). Closes WARP-57 SENTINEL MEDIUM-4. py_compile clean. No schema change. STANDARD, FUNCTIONAL.
2026-05-21 14:23 | WARP/warp56-sentry-p0-fix | WARP-56 (issue #1257): 3 Sentry P0/P1 fixes — services/signal_scan/signal_scan_job.py `_coerce_jsonb` narrowed so JSON scalar/wrong-shape values return fallback instead of leaking to `strategy.initialize()` (was ValueError: dictionary update sequence element); domain/risk/gate.py `_log` catches asyncpg.ForeignKeyViolationError at DEBUG so /admin/dry-run with synthetic user_id stops paging Sentry on every tick; migrations/001_init.sql drops `access_tier SMALLINT` from users CREATE TABLE (fresh-install DDL only — live DB already dropped via mig 044); historical access_tier comments rewritten in migs 024/031/045. 15 new + 77 existing hermetic tests pass. No schema change. STANDARD, NARROW INTEGRATION.

## [WARP-68] Structured card format + positions pagination — MERGED b7355541d496
**Date:** 2026-05-23
**PR:** #1287 | **Branch:** WARP/warp68-structured-card-ui | **Tier:** STANDARD

## [WARP-67] Telegram UX final clean — MERGED 2989b7c6e788
**Date:** 2026-05-22
**PR:** #1285 | **Branch:** WARP/warp67-ux-final-clean | **Tier:** STANDARD

B1: Flat Markdown format (no Unicode box-drawing chars, md\_escape, parse\_mode=Markdown).
B2: main\_menu\_kb configured param — Auto Mode when preset set but stopped.
B3: autotrade home\_kb paused param — Start/Pause/Resume state-correct.
B4: Settings+Help → \_group0\_noop (single response only).
B5: md\_escape+strip on market titles. 1614 passed.

## [WARP-66] Telegram UX polish — MERGED ab6f397f2741
**Date:** 2026-05-22
**PR:** #1283 | **Branch:** WARP/warp66-ux-polish | **Tier:** STANDARD

6 UX fixes: ReplyKeyboard routing (all 5 buttons wired dispatcher.py group=-1),
autotrade STATUS_STOPPED, copy_wallet STATUS_STOPPED, returning user keyboard re-attach,
dashboard 🤖→🔄 Auto Trade emoji dedup, strategy label from PRESET_CONFIG. 1614 passed.

## [SENTINEL RE-AUDIT] APPROVED 96/100 — MERGED d42b7e915356
**Date:** 2026-05-22
**PR:** #1281 | **Branch:** WARP/sentinel-reaudit-2026-05-22 | **Issue:** #1276

Prior BLOCKED (60/100) verdict lifted. Score 96/100, zero critical findings.
H1–H8 all PASS. H2 (threading) CLEARED. F-002 (copy_targets drift) CLEARED.
1613 passed, 0 failed. Residual P2 deferred (duplicate CopyTradeStrategy + copy_targets orphan).

## [SENTINEL] CrusaderBot Core Audit 2026-05-21 — BLOCKED ac1c207f2238
**Date:** 2026-05-22
**PR:** #1272 | **Branch:** WARP/sentinel-core-audit-2026-05-21 | **Score:** 60/100

Verdict: BLOCKED — H2 threading.Lock violation in registry.py (F-001 P0).
7/8 subsystems PASS. Risk gate, execution router, kill switch, WebTrader, Telegram, confluence scalper, DB migrations all clean.
Fix cycle open: WARP-62 (P0 threading) + WARP-63 (P1 copy_targets drift).

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

## [2026-05-23] SYSTEM AUDIT — WARP/crusaderbot-system-audit (BLOCKED 62/100)

- WARP•SENTINEL CORE AUDIT pre-client-handoff vs main HEAD 9caaabc + blueprint v3.1
- F-CRIT-1 (BLOCKER): bot/ui/__init__.py imports BAR/BRANCH/LAST/STATUS_*/PAPER/LIVE/LOCKED removed from bot/ui/tree.py (WARP-67/68/71/73) → main.py→bot.dispatcher→MVP handlers ImportError; app cannot boot from main
- F-HIGH-2: 0 positions/orders/fills/snapshots live (6 users, 5 auto-on) — frontend empty
- PASS: risk constants/gate/guards/kill switch/asyncio/no-silent-fail; realtime NOTIFY triggers wired; 1606 pytest pass; ruff clean; frontend build clean; blueprint conformance high
- Live verified via Supabase + Sentry + GitHub MCP (secrets not injected locally)
- Report: projects/polymarket/crusaderbot/reports/sentinel/crusaderbot-system-audit.md
- Gate: BLOCKED — fix F-CRIT-1 + redeploy + re-validate before handoff

