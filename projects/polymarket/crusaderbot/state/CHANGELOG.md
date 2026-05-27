<!-- gate-notify-verify-v3 -->
2026-05-27 13:30 | WARP/ROOT/supabase-function-search-path | H2 audit fix: migration 059 — SET search_path = public, pg_catalog on all 9 mutable-search_path functions (_cb_notify_fills/orders/portfolio_snapshots/positions/system_alerts/system_settings/user_settings + positions_reject_applied_tpsl_update + positions_snapshot_applied_tpsl). All 9 WARN cleared from Supabase security advisor. MINOR.
2026-05-27 12:00 | WARP/ROOT/bot-html-to-markdownv2 | H3: migrated all 26 legacy bot/handlers from ParseMode.HTML to ParseMode.MARKDOWN_V2 — removed html.escape(), added _md() for dynamic content, escaped MD2 specials in static strings, wrapped financial values in code spans. STANDARD, NARROW INTEGRATION. Report: reports/forge/bot-html-to-markdownv2.md.
2026-05-26 20:15 | WARP/R00T-copy-targets-migration | WARP-57 MEDIUM-4: retire copy_targets — migration 058 backfills remaining rows to copy_trade_tasks + DROP TABLE; _legacy_list_active/_insert_active_target/_legacy_deactivate_target + setup.py all redirected to copy_trade_tasks; 3 test SQL patterns updated. 1792 pass; ruff clean. STANDARD, NARROW INTEGRATION. Report: reports/forge/copy-targets-migration.md.
2026-05-26 19:30 | WARP/R00T-wallet-deposit-withdraw | Deposit UX polish + full paper withdraw flow: migration 057 (withdrawals table + withdrawal_approval_mode), wallet/withdrawals.py DB layer (atomic ledger debit/refund), Telegram UX (amount→address→confirm→submit), admin approval panel (/admin withdrawals), AUTO/MANUAL toggle in system_settings. Operator + user Telegram notifications wired. 18 new tests; 1792 pass; ruff clean. STANDARD, NARROW INTEGRATION. Report: reports/forge/wallet-deposit-withdraw.md.
2026-05-26 17:15 | WARP/R00T-sse-session-pooler-listen | Fix SSE LISTEN reconnect-loop (Sentry DAWN-SNOWFLAKE-1729-23, Errno 111) — _normalize_dsn_for_listen no longer rewrites pooler URL to dead direct host db.<ref>.supabase.co:5432; keeps pooler host, switches transaction port 6543→session 5432 (session pooler supports LISTEN). Removed unused import re. 5 new tests; 1774 pass; ruff clean. STANDARD, NARROW INTEGRATION. Report: reports/forge/sse-session-pooler-listen.md.
2026-05-26 17:00 | WARP/R00T-mock-clob-parity | SENTINEL MAJOR live execution path audit CONDITIONAL 84/100, 0 critical — MockClobClient get_usdc_balance() stub; RISK_CONTROLS_VALIDATED + SECURITY_HARDENING_VALIDATED enforced in assert_live_guards() + _passes_live_guards(); Kelly assert → raise ValueError; 2 new guard tests; 1769 tests pass. Report: reports/sentinel/live-execution-path.md.
2026-05-26 16:45 | WARP/R00T-preset-activate | SENTINEL APPROVED 91/100 — 5 new hermetic tests (min_entry_sec floor + underdog_mode); test_preset_picker_is_two_col updated for 3 visible presets; 1767 tests pass. Report: reports/sentinel/preset-activate.md.
2026-05-26 16:30 | WARP/R00T-preset-activate | Safe Close + Flip Hunter activation — late_entry_v3 extended (min_entry_sec floor for safe_close 30–60s window; underdog_mode for flip_hunter cheap-side 0.26–0.35 entry); _CANDLE_PRESET_PARAMS dict-format; config PRESET_SAFE_CLOSE_MIN_ENTRY_SEC + PRESET_FLIP_HUNTER_FAV_PRICE_MAX; router _PRESET_PARAMS + _CRYPTO_SHORT_PRESETS + tf_params unlocked; frontend STRATEGY_PRESETS + VISIBLE_PRESET_ORDER updated. 122 tests pass. MAJOR, NARROW INTEGRATION. Report: reports/forge/preset-activate.md.
2026-05-26 15:00 | claude/zealous-brahmagupta-LZaZV | WebTrader branding + recent-activity polish — dual logo: shield emblem (text-less, alpha-trimmed) in TopBar+Sidebar, full wordmark on login page; removed "TACTICAL · POLYMARKET" header subtitle (+ unused AdvancedOnly import); redesigned Recent Activity carousel to full-width HUD card (question+PnL, status pill, $size·SIDE@price¢·time, View all→portfolio); deleted old crusaderbot-logo.png. MINOR. Report: reports/forge/logo-and-recent-activity.md.
2026-05-26 14:10 | claude/zealous-brahmagupta-LZaZV | WebTrader Emergency Stop — sidebar button now real: POST /emergency-stop activates kill switch + marks all open positions force_close_intent=TRUE (watcher closes at market price, profit or loss), mirroring Telegram pause+close-all. Two-click confirm in DesktopSidebar. Reuses kill_switch.set_active + mark_force_close_intent_for_user (no new close logic). MAJOR, SENTINEL APPROVED 94/100 (by WARP•R00T). Reports: reports/forge/webtrader-emergency-stop.md + reports/sentinel/webtrader-emergency-stop.md.
2026-05-26 13:30 | claude/zealous-brahmagupta-LZaZV | Pre-launch polish — DesktopSidebar brand header (logo + CRUSADERBOT title, BASE_URL path, 32x21); migration 055 scan_runs RLS formalized in repo; state files synced to reflect PRs #1354+#1355 merged. MINOR.
2026-05-27 00:00 | claude/zealous-brahmagupta-LZaZV | Pre-public gate sweep — Gate 1: trades verified flowing (722 pos/24h). Gate 2: migration 055 RLS on scan_runs → 43/43 tables locked. Gate 4: 119 bad tp_hit positions corrected in-place (qwneer8 87 pos $596→$124 pnl, Maver1ch69 32 pos $175→$26 pnl); wallet balances clawed back (qwneer8 $1255→$788, Maver1ch69 $995→$846). Gate 3+5 observation-only (monitoring).
2026-05-26 23:30 | claude/zealous-brahmagupta-LZaZV | Home enhancements + exit_price TP/SL fix — scanner status strip (last tick + signals_today + candidates, always visible), open positions defaultExpanded in Home, recent activity slide (5 latest closed tiles), "IN" size label in PortfolioPage meta; exit_watcher.evaluate() TP_HIT/SL_HIT now return exact threshold price (_tp_exit_price/_sl_exit_price) not sampled market price (fixes +1244% P&L inflation from polling lag). 1762 tests pass. STANDARD, NARROW INTEGRATION. Report: reports/forge/home-enhancements.md.
2026-05-26 19:20 | claude/zealous-brahmagupta-LZaZV | User max-$-per-trade control (#3) — three modes: auto ($25 system default, behaviour unchanged), fixed (max_per_trade_usdc bounded [$1,$500]), pct (max_per_trade_pct of equity bounded [0.5%,10%]). New late_entry_v3.resolve_per_trade_ceiling() + suggested_trade_size(ceiling_usdc=) — used by BOTH the strategy and GET /autotrade so the UI "Max per trade" matches the engine. UserContext += 3 fields; signal_scan_job wires them; AutoTradeState computed field renamed -> effective_max_per_trade_usdc + echoes mode/usdc/pct; CustomizeRequest + /customize persist them (mode validated auto|fixed|pct); MaxPerTradeControl UI (mode buttons + bounded input) in Risk Profile. Migration 053 (max_per_trade_mode/usdc/pct + CHECK) APPLIED to prod (additive/idempotent). Hard system ceilings ($500/10% + Kelly + 10% position fence) enforced in code regardless of DB values. 1760 tests pass (+3) + ruff clean. MAJOR, NARROW INTEGRATION. Report: reports/forge/user-max-per-trade.md. NEXT: #4 daily $-loss + max drawdown %.
2026-05-26 18:40 | claude/zealous-brahmagupta-LZaZV | Equity-based sizing + "Max per trade" UI clarity (#1+#2) — per-trade size now sizes off EQUITY (free balance + open-position cost) not idle cash: UserContext.equity_usdc (default 0.0, falls back to available_balance); signal_scan_job user-query += open_cost_usdc subquery, _build_user_context computes equity. New shared late_entry_v3.suggested_trade_size(base, cap%) = clamp(base x cap% x 4%, $1, $25), used by BOTH the strategy and GET /autotrade. AutoTradeState += equity_usdc + max_per_trade_usdc; AutoTradePage Risk Profile shows "Max per trade: $X · CAP N% of $E equity is the deployable pool, not one trade" — kills the "60% = $600/trade" misread (real = equity x cap% x 4%, capped $25). PR #1346 + #1347 confirmed MERGED + deployed (builds f51fd09, 43f590d). 1757 tests pass (+2 new: suggested_trade_size floor/cap, sizes-off-equity) + ruff clean. MAJOR, NARROW INTEGRATION. Report: reports/forge/equity-sizing-and-max-per-trade.md. NEXT: lane #3/#4 user-set max $/trade + max daily drawdown (SENTINEL-gated).
2026-05-26 17:55 | claude/zealous-brahmagupta-LZaZV | Expandable trade-detail view (PR #1347) — WebTrader position cards now tap-to-expand (PositionCard new `detail` prop + expand state + chevron; footer/detail clicks stopPropagation). Detail shows Entry time+price, Exit time+price (BLANK "—" while open, fills on close), TP price, SL price, and "Closed By" full label (Take Profit / Stop Loss / Expired Time / Market Resolution / ...). Backend: GET /positions returns tp_pct, sl_pct, tp_price, sl_price; new `_tp_sl_price()` derives side-aware trigger levels in YES-price units mirroring paper.close_position. Built after owner re-flagged "5 detik" — root cause was misreading the 5-minute candle market name ("10:50PM-10:55PM") as trade duration; that trade actually held ~29s (DB-confirmed). ast clean; tsc/pytest not in env (CI gate). STANDARD, NARROW INTEGRATION. Report: reports/forge/trade-detail-expandable-view.md.
2026-05-26 17:30 | claude/zealous-brahmagupta-LZaZV | late_entry_v3 favored-price ceiling — owner reported "5-second trades / profit anomaly"; DISPROVEN via Supabase (holds 26-31s TP/SL, 0 trades under 10s — _past_end bug still fixed). Real issue: negative edge (last 3h 60 SL -$265 vs 32 TP +$148 = -$114). Bucketing closed trades by favored entry price: fav 0.70-0.93 = -$188 over 94 trades at 17-31% win (the -99% SLs, e.g. ETH YES@0.835 -> exit 0.005); fav 0.55-0.69 = +$278. Fix: config LATE_ENTRY_FAV_PRICE_MAX (new, default 0.70, env-tunable) + module FAV_PRICE_MAX 0.93->0.70; fav_price_max threaded through scan()+_evaluate_market; gate now uses the param; scan_summary log adds fav_price_max. Tests: positive-entry fixtures 0.70->0.65, +2 boundary tests (reject 0.72 / enter 0.68). ast clean (pytest not installed in env). MAJOR, NARROW INTEGRATION — SENTINEL/WARP🔹CMD review. Report: reports/forge/late-entry-fav-price-ceiling.md.
2026-05-26 17:05 | claude/zealous-brahmagupta-LZaZV | Persist positions.market_question (follow-up on #1346 finding) — domain/execution/paper.py + live.py INSERT INTO positions now writes market_question (value already available on the signal at open time, was dropped at INSERT); webtrader/backend/router.py 4 position read queries switched m.question -> COALESCE(m.question, p.market_question[, p.market_id]). Candle markets are ephemeral; once a markets row is pruned the label JOIN would degrade to a raw hash — this makes Port/Activity/closed-position labels durable. Historical rows stay NULL (still label via live markets JOIN). py_compile clean; hermetic paper.execute test unaffected (fake fetchrow ignores args). STANDARD, NARROW INTEGRATION.
2026-05-26 16:40 | claude/zealous-brahmagupta-LZaZV | Close Sweep asset options expanded — added HYPE/XRP/DOGE as opt-in crypto-short assets (webtrader/frontend AutoTradePage CRYPTO_ASSETS -> 7 coins + new CRYPTO_ASSETS_DEFAULT=["BTC"]; webtrader/backend router _CRYPTO_SHORT_ASSETS -> 7 + _DEFAULT_CRYPTO_SHORT_ASSETS=("BTC",) empty-selection default; Home-feed coin filter + asset_labels extended). Default active selection now BTC only; thinner-book coins opt-in. eligibility.ASSET_ALIASES already mapped all 7. Verified all 7 have live Polymarket {coin}-updown-{tf}-{slot} markets. Also DIAGNOSED owner "only BTC/ETH open" report as NOT a bug: per-user Supabase audit shows every late_entry_v3 user trades all four majors (e.g. user 7e6fbd20 = BTC 101/ETH 84/SOL 68/BNB 9); SOL ~26%, BNB ~3% (thin books); live view only shows the current candle window. Secondary finding logged (unfixed): paper.execute omits market_question from INSERT (NULL on all rows; UI unaffected, labels via markets.question JOIN). STANDARD, NARROW INTEGRATION. Report: reports/forge/close-sweep-asset-options.md.
2026-05-26 09:02 | WARP/state-sync-2026-05-26 | State reconciliation — synced PROJECT_STATE.md + WORKTODO.md to repo reality after verifying 0 open PRs on GitHub and bot runtime via Supabase (project ykyagjdeqcgcktnpdhes). Confirmed all prior "open" lanes are MERGED and in main: WARP-TDC trade-diversity (_diversify_order + PROFILES 5/12/20), WARP-CTP crypto-timeframe-presets (is_short_crypto_market/classify_crypto_timeframe), WARP-LEF late-entry-fast-window (run_close_sweep_fast + LATE_ENTRY_WINDOW_SEC=35), WARP-AUTH-PWD bcrypt 72-byte guard (#1340). late_entry_v3 verified FILLING: 670 closed trades, +$515 USDC paper PnL, 0 trades under 10s (the 5-second exit_watcher _past_end bug confirmed gone via #1344). FLAGGED for monitoring before public scale: direction win-rate 46% (260 tp_hit / 300 sl_hit), net PnL positive only via market_expired (+$477 / 78 trades). RLS verified ENABLED on 42/43 public tables. Rewrote stale [IN PROGRESS] + [NEXT PRIORITY] blocks (merged-PR noise -> genuine priorities) and fixed the RLS DISABLED-vs-RESOLVED contradiction in [KNOWN ISSUES]. Doc/state-only, no code change. MINOR.
2026-05-25 11:11 | main (direct) | Runtime stabilization: DB pool 4→10, gate step-4 strategy allowlist, gate step-11 user liquidity floor, market end-time auto-close, FLIP_STOP 0.48→0.10, WebTrader UI polish (risk tag colors, SSE live dot, entry price, empty state), Telegram UX overhaul (preset picker, main menu wallet button, dashboard clarity, close_sweep metadata fix), new user defaults (aggressive/close_sweep/bot OFF), scanner market filter settings wired, two-sided CLOB depth for liquidity gate, Sentry #7504244313 resolved
2026-05-25 04:29 | WARP/close-sweep-pipeline-fix | WARP-47 Close Sweep pipeline fix — 4 bugs causing 0 fills post-deploy: BUG1 (CRITICAL) market_id=conditionId (_evaluate_market was using Gamma UUID, _load_market never resolved); BUG2 (CRITICAL) get_live_market_price now uses condition_ids (plural) + validates conditionId before caching (was pricing positions against wrong markets); BUG3 (HIGH) active gate skipped for updown candle slugs (Polymarket sets active=False before resolution while CLOB live); BUG4 (MEDIUM) per-gate debug logs + scan_summary at INFO + close_sweep_fast_tick at INFO. Config vars LATE_ENTRY_MIN_ASK_DIFF/WINDOW_SEC/FLIP_STOP added for runtime tuning. 3 new tests. py_compile clean. STANDARD, NARROW INTEGRATION.
2026-05-25 00:45 | WARP/state-sync-close-sweep | WARP-SYNC state sync — Close Sweep lane complete + deployed. Merged this run: #1325 late_entry_v3 + exit dispatch + Trade-Blocked-notif removal, #1326 candle resolution/settlement, #1327 AUTO_REDEEM_ENABLED=true, #1328 ENTRY_WINDOW_SEC=35 + 15s close_sweep_fast loop, #1329 awaiting_redeem + Force Redeem + settle snapshot, #1330 WebTrader Home open-positions + realtime, #1331 (owner) Home redeem-PnL/carousel/market-feed, #1332 late_entry_v3 best-ask fix + MIN_ASK_DIFF 0.05. Verified live: candles resolve + settle, winner redeemed. OPEN: confirm late_entry_v3 fills post-#1332 (0 as of 17:15, ~deploy time) via positions WHERE strategy_type='late_entry_v3'; if still zero, lower MIN_ASK_DIFF or add a fast-loop diagnostic log; profitability unvalidated. Doc/state-only.
2026-05-25 00:15 | WARP/late-entry-ask-fix | WARP-LAF late_entry_v3 ask-reading fix + threshold calibration — "make sure it trades": strategy emitted 0 candidates in prod (scan_runs late_entry_v3:filter_or_no_match, no risk rejection). Live CLOB probe found two bugs: (1) _best_ask used asks[0] but Polymarket CLOB /book returns asks DESCENDING (asks[0]=highest ~0.99), so both sides priced ~1.0 -> ask_diff~0 + fav_price>=0.93 -> always filtered; fixed to min(price) over asks (order-independent). (2) MIN_ASK_DIFF=0.30 far too strict — BTC/ETH 5m/15m candles sit ~0.50/0.50 (best asks YES 0.50/NO 0.51); lowered to 0.05. Other gates + risk-gate sizing unchanged; paper-only; no migration. 1750 tests pass / 1 skip (threshold test ->0.02 skip, new small-lean entry + _best_ask ordering tests). MAJOR -> SENTINEL. Profitability unvalidated — watch first fills.
2026-05-24 23:30 | WARP/webtrader-home-positions | WARP-WHP WebTrader Home open positions + realtime + Force Redeem (frontend, consumes WARP-FRA/#1329). (1) DashboardPage Home "Live Market Feed" (signals) replaced with the user's OPEN POSITIONS via shared PositionRow (exported from PortfolioPage). (2) Home+Portfolio subscribe to the full position/portfolio SSE set (+ position_updated + portfolio) and add a 15s setInterval polling fallback for SSE stalls. (3) PositionItem.awaiting_redeem cards show "WON · AWAITING REDEEM" + a Force Redeem button -> api.forceRedeem(id) (POST /positions/{id}/redeem) then refresh. tsc --noEmit clean; vite build OK (881 modules); not browser-tested here. STANDARD, NARROW INTEGRATION. Deploy with #1329.
2026-05-24 23:05 | WARP/force-redeem-awaiting-state | WARP-FRA force redeem + awaiting-redeem state + settlement snapshot — owner: won Close Sweep position showed "open / stuck not closed" (it's a winner whose owner uses hourly auto-redeem, queued up to 1h). Keep hourly but make it visible + actionable: (1) PositionItem.awaiting_redeem (open + market resolved + winning_side==side) for a "waiting hourly redeem" UI label; (2) POST /api/web/positions/{id}/redeem Force Redeem runs instant_worker.try_process on the pending redeem_queue row (user-scoped, 409 when none); (3) settle_winning/settle_losing write_snapshot(user_id) (best-effort) so cb_portfolio NOTIFY pushes equity/PnL to SSE on settlement. No settlement math change; reuses instant_worker (paper-safe, on-chain skipped). 1748 tests pass / 1 skip (5 new test_webtrader_positions). MAJOR -> SENTINEL. Frontend (button + label + Home open-positions + realtime SSE) is the next PR.
2026-05-24 22:30 | WARP/late-entry-fast-window | WARP-LEF Late Entry V3 final-~35s window + dedicated fast scan — owner observed (Kreo Close Sweep screenshot) the edge enters only in the final ~35s (5m 265-299s, 15m 865-899s). (1) ENTRY_WINDOW_SEC 240->35 in late_entry_v3.py. (2) new signal_scan_job.run_close_sweep_fast() + scheduler job close_sweep_fast_scan @ CLOSE_SWEEP_SCAN_INTERVAL=15s — the 180s main scan would step over a 35s window; fast loop scans only close_sweep users + only late_entry_v3, writes no scan_runs row (in-memory telemetry), reuses existing helpers; _process_candidate dedup makes overlap with run_once Phase-B2 harmless; caches (window 20s/book 30s) bound API load. Risk gate/sizing UNCHANGED, guards untouched (paper-only), no migration. 1743 tests pass / 1 skip (3 new run_close_sweep_fast cases + late_entry window fixtures + 3 scheduler-fixture settings gain CLOSE_SWEEP_SCAN_INTERVAL). MAJOR -> SENTINEL.
2026-05-24 22:05 | WARP/enable-auto-redeem | WARP-ARE enable auto-redeem settlement — one-line fly.toml flip AUTO_REDEEM_ENABLED "false"->"true". detect_resolutions() returns at its first guard when the flag is false, so the resolution/settlement scan no-opped in prod (job_runs 'resolution' ~1ms/0-work every 5 min) — the candidate query DOES return the 5 stuck candle positions, so the flag was the only remaining gate after #1326. Code default is True (paper-mode intent) and owner sets auto-redeem per-user in the web terminal; the global fly.toml override short-circuited it. Paper-only (ENABLE_LIVE_TRADING=false -> on-chain skipped); first post-deploy resolution tick settles all past-due resolvable positions. No code change, no tests affected. STANDARD, NARROW INTEGRATION.
2026-05-24 21:40 | WARP/candle-resolution-settlement | WARP-CRS candle resolution + settlement — fixes owner report "Close Sweep positions just open, never close at end time". Diagnosed live: 778 updown candle markets, 0 ever resolved, 5 positions stuck 'open' past resolution_at. ROOT CAUSE (capital-critical, affects ALL settlement): integrations/polymarket.get_market() used GET /markets?conditionId= (singular) which Gamma IGNORES — returns the default market list (an unrelated market) for any id, so detect_resolutions read the wrong market and never saw closed=true. FIX1 get_market -> plural ?condition_ids= + validates returned conditionId == requested (None on mismatch). FIX2 candle markets are not in /markets (only /events?slug=); new get_event_market_by_slug(slug) + _process_market_resolution slug-fallback (conditionId-validated) when get_market is None. FIX3 _coerce_outcome_prices() handles JSON-string outcomePrices ('["1","0"]'). detect_resolutions selects+passes markets.slug; settle/pending paths unchanged. 5 stuck positions auto-settle next resolution tick post-deploy. 1740 tests pass / 1 skip (9 new test_candle_resolution), py_compile clean, guards untouched (paper-only), no migration. Only 2 get_market callers (copy_trade meta + redeem) both benefit. MAJOR -> SENTINEL.
2026-05-24 20:45 | WARP/late-entry-v3 | WARP-LEV Late Entry V3 — new domain strategy (domain/strategy/strategies/late_entry_v3.py) replaces expiration_timing as the Close Sweep engine (the real edge, ref polybot_4coin): enters the final 240s on live BTC/ETH/SOL/BNB 5m/15m candles, buys the higher-CLOB-ask favored side when ask-diff>=0.30 & favored<0.93 & combined-asks<=1.05, sizes via the WARP risk gate (suggested $ -> fractional Kelly + caps, not fixed contracts), and flip-stops at 0.48. Exit path made real: exit_watcher rewired from the no-op default_strategy_evaluator to registry_strategy_evaluator (dispatches evaluate_exit by positions.strategy_type with the live favored price; now default for evaluate/run_once/run_forever); OpenPositionForExit + list_open_for_exit carry strategy_type; paper.py/live.py positions INSERT now persist strategy_type (was NULL). Routing: _PRESET_ALLOWED['close_sweep']->{late_entry_v3}, STRATEGY_AVAILABILITY/bootstrap/__init__ register it, Phase-B2 scan invocation added, dead expiration_timing close_sweep branch removed. ALSO removed the noisy "Trade Blocked" Telegram notification per owner (engine.py trade.blocked emit + _blocked_reason_display + notification_service handler/subscription/cooldown deleted; rejections still recorded in scan_runs.rejection_breakdown). 1731 tests pass / 1 skip (18 new), py_compile clean on 11 files, guards untouched (paper-only), no migration (positions.strategy_type via mig 034/041). MAJOR -> SENTINEL.
2026-05-24 14:35 | claude/crusaderbot-signal-scan-debug-Xnckj | WARP-TDC trade diversity + concurrency — fixes beta #1 "bot only trades the same ~5 markets". (A) services/signal_feed/signal_evaluator.py: publications were loaded in identical published_at-ASC order for every subscriber and entered until the cap, so all 5 users converged on the same markets; new _diversify_order() orders each user's candidates by sha1(user_id:market_id) — deterministic per (user,market) so distinct holdings without inter-tick churn; candidates already passed edge/liquidity/horizon filters; single point covers signal_scan_job.run_once + SignalFollowingStrategy.scan. (B) domain/risk/constants.py: PROFILES max_concurrent raised 3/5/5 -> 5/12/20 (custom 12); 40% correlated-exposure fence still bounds total exposure (more, smaller, diverse positions). Fixed risk fences UNTOUCHED (Kelly 0.25 / max 10% pos / daily -$2k / 8% drawdown / 40% exposure). 6 new tests (test_signal_diversity.py) + 195 scan/pipeline + 109 following/smoke + 50 gate green; guards untouched (paper-only). No migration. MAJOR -> SENTINEL. Lane 1 (category mapping) blocked on gamma-api network allowlist; Lane 3 (edge-model longshot bias) queued.
2026-05-24 13:20 | claude/crusaderbot-signal-scan-debug-Xnckj | WARP-RMS real-market settlement fix — root cause of beta "same ~5 positions, 0 PnL, slots never free". FIX1 (CRITICAL) integrations/polymarket.get_market(): GET /markets/{hex} path-segment returns 422 for hex conditionIds (markets.id IS the condition_id via scanner + market_sync), so detect_resolutions->_process_market_resolution->get_market() 422'd on every position -> no market ever observed closed -> nothing settled -> concurrency slots locked forever; rewrote to GET /markets?conditionId= query form (mirrors get_live_market_price). FIX2 jobs/market_signal_scanner.py + config.py: edge-finder (already real Gamma data) now publishes to the LIVE feed with is_demo=FALSE by default; new SCANNER_DEMO_FEED_ENABLED (default False) reserves the is_demo=TRUE/demo-feed path for hermetic tests + dev. FIX3 services/redeem/redeem_router.py + domain/risk/gate.py: pending_settlement status — real market past resolution_at without official resolution flipped open->pending_settlement (never flat-closed, never marked from last price), counted in exposure, settles on official close. Settlement was already official-only; the 422 just made it unreachable. 18 redeem (2 new) + 13 scanner (2 new) + 62 signal/pipeline tests green. Guards untouched (ENABLE_LIVE_TRADING=false, paper-only). No schema migration (status has no CHECK constraint). MAJOR -> SENTINEL. PENDING PROD OPS (owner-authorized, not executed): void 25 demo positions (return stake, pnl=0) + migrate 6 beta users Demo->Live feed.
2026-05-23 23:30 | WARP/operator-control-panel-async | WARP-OPC Operator Control Panel (async adapt-intent of the background-process+Telegram-control handoff; arbibot threading/SQLite pattern rejected). Part A: run_signal_scan returns pipeline metrics dict (captured into job_runs.metadata via existing listener) + _process_candidate returns outcome strings — additive, behaviour-preserving. Part B: /panel operator-only inline panel (Start/Stop/Lock/Status/Stats/Settings/Help) composing existing kill-switch + dashboard + job_tracker (new fetch_latest); bot/handlers/operator_panel.py + keyboards/admin.operator_panel_keyboard + dispatcher wiring. No threading/SQLite/fly.toml change; PAPER only, guards untouched. py_compile clean; runtime/pytest not exercised (asyncpg absent + cryptography Rust panic in container). MAJOR, NARROW INTEGRATION. SENTINEL gate pending.
2026-05-23 17:49 | WARP/runtime-trade-smoke | WARP-43 runtime trade smoke — scan_runs telemetry (migration 048), ScanTelemetry dataclass + skip/rejection/approval accumulation, structured log events (strategies_loaded/scan_input/strategy_run/risk_gate/paper_execution), startup loud-fail RuntimeError guard, GET /admin/scan/last + GET /admin/scan/list; hermetic smoke test (14 cases). STANDARD, NARROW INTEGRATION.
2026-05-23 22:12 | WARP/CRUSADERBOT-DEPOSIT-REORG-GUARD | WARP-42 Lane C (H6) MERGED PR #1305 — deposit confirmation-depth + reorg guard. DEPOSIT_CONFIRMATION_DEPTH=32 + migration 047 (additive/idempotent, backfills legacy rows to confirmed) + scheduler.watch_deposits rewritten to pending→confirmed (credit at depth)→reverted (un-credit on removed=true) state machine + polygon.py surfaces log removed flag. 4/4 new tests (test_deposit_reorg.py) + existing test_sweep_deposits.py green. Prophylactic, behind ENABLE_LIVE_TRADING=False. STANDARD.
2026-05-23 22:08 | WARP/CRUSADERBOT-CONFIG-GAPS-PATCH | WARP-42 Lane B MERGED PR #1304 — config.py SECURITY_HARDENING_VALIDATED guard added (default False, closes §12/M-5) + AUTO_REDEEM_ENABLED paper-intent comment (no value change). MINOR.
2026-05-23 22:05 | WARP/CRUSADERBOT-BLUEPRINT-V3.3-SYNC | WARP-42 Lane A MERGED PR #1303 — docs/blueprint/crusaderbot.md v3.2→v3.3 code-reality reconciliation per WARP-41 (edits A1–A13); decision-items defaulted with DECISION-NEEDED markers (2FA deferred / fee 10% / roadmap dual-scheme / referrer_id unwritten). Doc-only. MINOR.
2026-05-23 20:30 | WARP/CRUSADERBOT-RUNTIME-BUGFIX | WARP-40 Lane 2 runtime bugfix (DAWN-5/1K/1Q) — FIX1 exit_watch dict→str (job_runs json.dumps→$6::jsonb) and FIX2 access_tier UndefinedColumnError (zero column refs, users.role gating) verified already-resolved in code, no change; FIX3 added isinstance(dict) guard on per-strategy strategy_params sub-value in signal_scan_job.run_once (drops malformed non-dict to {} + logs) on top of existing _coerce_jsonb top-level guard. 1-file delta. py_compile clean. STANDARD, NARROW INTEGRATION. WARP🔹CMD review only.
2026-05-23 19:40 | WARP/CRUSADERBOT-INFRA-STABILITY | WARP-39 infra-burn lane — statement_cache_size=0 added to the two one-off operator scripts (cleanup_demo_data.py:208, seed_demo_data.py:469) so all asyncpg connect/pool paths disable the prepared-statement cache (DAWN-6..X); max_machines_running=1 added to fly.toml for Telegram single-instance (DAWN-14). FIX3 (pool min/max + clean close + pool-reusing health check) and FIX4 (validate_required_env lists all missing vars) verified already-satisfied — no change. 3-file delta. MAJOR, NARROW INTEGRATION. SENTINEL pending.

## [F-HIGH-2] lib strategy load fix — WARP/lib-strategy-load-fix
**Date:** 2026-05-23 | **Tier:** MAJOR | **Status:** pending SENTINEL

## [F-HIGH-2] Vendor lib/ into crusaderbot — prod strategy load fix — MERGED e235fa294823
**Date:** 2026-05-23 | **PR:** #1298 | **Tier:** MAJOR | **SENTINEL:** 99/100 APPROVED

lib/ vendored into projects/polymarket/crusaderbot/lib/.
Loader _LIB_PKG derived via __package__ — dev/prod gap closed.
7/7 strategies load, 60 tests pass. No content change to lib classes.
F-HIGH-2 resolved — paper trades will flow on next deploy.


Primary F-HIGH-2 cause: lib/ auto-trade strategies never produced candidates —
(1) lib/ lived at repo root, outside the crusaderbot Docker build context, so it
was never shipped to prod; (2) the file-path loader (spec_from_file_location)
could not resolve the strategies' package-relative imports → ImportError for every
strategy even when present. Fix: relocated lib/ into the crusaderbot package
(git mv), added lib/__init__.py + lib/strategies/__init__.py (get_strategy), and
rewrote lib_strategy_runner._load_strategy to import strategies as package
submodules (pkg root derived from __package__; dev+prod safe). lib classes
unmodified. All 7 lib strategies now load (was 0). 1628 pytest pass / 1 skip / 0
fail; ruff clean. New regression suite tests/test_lib_strategy_loading.py (15).
Live trade generation to confirm post-deploy. Phase C feed-eval is a separate
open follow-up. Forge report: reports/forge/lib-strategy-load-fix.md.

## [SECURITY-RLS] Enable RLS on all 42 public tables — anon-key lockout
**Date:** 2026-05-23 | **Branch:** WARP/rls-enable-anon-lockout | **Tier:** MAJOR

## [RLS-046] Enable RLS all 42 public tables — MERGED 82f08af2a27b
**Date:** 2026-05-23 | **PR:** #1296 | **Tier:** MAJOR | **SENTINEL:** 98/100 GO-LIVE APPROVED

migration 046: ENABLE ROW LEVEL SECURITY on all 42 public schema tables.
anon/authenticated denied by default. postgres/service_role bypass RLS — backend unchanged.
Closes Supabase advisor CRITICAL finding (rls_disabled).


Supabase advisor (CRITICAL): all 42 public tables RLS-disabled → anon/authenticated
key could read/write every row. migrations/046_enable_rls_anon_lockout.sql enables RLS
(no FORCE, no policies → deny-by-default for anon). Verified safe: tables owned by
postgres (BYPASSRLS) + service_role BYPASSRLS; frontend uses backend API/SSE only, no
direct anon path. Validated read-only: 42/42 names exist, covers all public tables, 0
already enabled. Drafted for review — NOT applied (auto-applies on next deploy via
database.py). Forge report: reports/forge/rls-enable-anon-lockout.md.

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

## [2026-05-24] WARP-TDH — Trade-Discovery Hardening (WARP/trade-discovery-hardening, PR open)

- Root cause (beta tester "same 5 futures, 0 profit, can't find other positions"): all 25 open positions across 5 auto-on users are far-dated 2026/2028 championship-winner futures (NHL/NBA/World Cup) locking every concurrency slot (cap 5/user)
- #2 resolution horizon now per-profile: signal_scan_job._build_market_filters() uses PROFILES (7/30/90d + liquidity floor) instead of the hardcoded 365 disable-sentinel; signal_evaluator enforces markets.resolution_at via LEFT JOIN (pure DB read — prior "needs HTTP" rationale was wrong)
- #3 demo scanner universe: market_signal_scanner fetches SCANNER_MARKET_FETCH_LIMIT=500 markets ordered by 24h volume with SCANNER_MAX_RESOLUTION_DAYS=30 cap (get_markets gains order/ascending/end_date_max; client-side guard) → far-dated futures never published
- #4 slot release: ExitReason.HORIZON_EXCEEDED + exit_watcher per-profile horizon exit (after TP/SL/strategy) frees stuck slots; OpenPositionForExit carries resolution_at + risk_profile (list_open_for_exit LEFT JOINs user_settings)
- 185 affected tests pass (test_exit_watcher +5 new horizon cases, scanner fixture updated, signal_following / signal_scan_job / copy_trade / confluence / momentum green); py_compile clean; guards untouched (ENABLE_LIVE_TRADING=false)
- Deferred: edge-model bug #1 (edge=|price-0.5| favours longshots) — separate strategy lane; the 20 aggressive-user futures are within their 90d mandate and are NOT auto-closed (owner decision)
- Report: projects/polymarket/crusaderbot/reports/forge/trade-discovery-hardening.md
- Gate: MAJOR → WARP•SENTINEL required before merge

## [2026-05-24] WARP-SST — Scan-Stats Truth-Source (WARP/scan-stats-truth-source, branch claude/crusaderbot-signal-scan-debug-Xnckj, PR open)

- Diagnosis: beta "0 candidates / ~5 trades/week" alarm ROOT-CAUSED to misleading telemetry, not a scan defect — two scan jobs run at SIGNAL_SCAN_INTERVAL; the legacy run_signal_scan (scheduler.py, copy_trade-only, markets_seen=0) writes job_runs(job_name=signal_scan, candidates_emitted=0), while the real feed-eval engine sf_scan_job.run_once writes scan_runs with candidates_emitted≈453/tick (strategies_loaded=11, markets_seen=100)
- #1312 verified working in prod: balanced user re-entered 5 diverse <7d positions (Hormuz/Knicks/US-Iran), no 2026/2028 futures; handoff hypotheses disproved (capital_alloc_pct fine, category_filters hardcoded [], PR #1298 already merged)
- Fix: signal_scan_job.fetch_latest_scan_run() reader; operator_panel /panel→Stats repointed to scan_runs + _summarize_breakdown() surfaces step_7_max_concurrent_trades + skipped_signal_stale; scheduler legacy job id signal_scan→legacy_copy_trade_scan (copy_trade NOT removed — architecture call deferred to CMD)
- 48/48 test_signal_scan_job.py pass (3 new fetch_latest_scan_run cases); py_compile clean on 3 files; render verified standalone; guards untouched (ENABLE_LIVE_TRADING=false)
- Real throughput limiter (all 5 users at MAX_CONCURRENT=5; 314/453 candidates stale) flagged as separate MAJOR lane
- Report: projects/polymarket/crusaderbot/reports/forge/scan-stats-truth-source.md
- Gate: STANDARD → WARP🔹CMD review (no SENTINEL)


2026-05-24 17:00 | claude/fervent-hawking-yNP0Z | Lane 3: edge-model-momentum — replaced abs(yes_p-0.5) scoring with 24h/1h momentum; tightened price range to 0.15-0.85; side follows momentum direction
2026-05-24 17:30 | claude/fervent-hawking-yNP0Z | Lane 1: category-mapping — get_events_with_markets() enriches market dicts with Gamma event tags; category filter now works for all dashboard categories

2026-05-24 19:10 | WARP/crypto-timeframe-presets | crypto-short presets (Crypto Scalper + Close Sweep) gated to 5m/15m short-duration crypto + category auto-lock (mig 049); Ensemble→Smart Mix; hide whale_mirror + Coming Soon in web
2026-05-24 19:45 | WARP/crypto-timeframe-detection-fix | fix is_short_crypto_market: identify crypto via asset-ticker + 5m/15m interval (not literal category) so real btc/eth-updown candle markets qualify; Close Sweep/Crypto Scalper now match live data
2026-05-24 20:30 | WARP/crypto-short-asset-selector | inline asset(BTC/ETH/SOL/BNB)+timeframe selector for crypto-short presets; selected_assets (mig 050); get_crypto_short_markets fetch-coverage so scanner sees live 5m/15m candle markets
2026-05-24 21:10 | WARP/crypto-window-slug-fetch | get_crypto_window_markets: deterministic current-window slug fetch ({coin}-updown-{tf}-{slot}) so scanner sees live in-window candles w/ liquidity; close_sweep volume/liq floors relaxed for micro candles
2026-05-24 21:45 | WARP/crypto-candle-market-upsert | upsert live crypto candle markets into markets table during scan so close_sweep/scalper candidates pass _load_market gate (was skipped_market_not_synced); carries CLOB token ids for execution
2026-05-24 11:50 | WARP/risk-gate-crypto-short-strategies | add expiration_timing + confluence_scalper to STRATEGY_AVAILABILITY so close_sweep/scalper candidates pass risk gate step 4 (was step_4_unknown_strategy reject)
2026-05-24 23:55 | WARP/webtrader-home-feed | WebTrader Home: WON-pending positions valued at redeem payout (fix WON-but-minus); awaiting-redeem split into own strip; open-positions auto-slide carousel (>1); compact CLOB market feed + GET /api/web/market-feed; news feed deferred (host not allowlisted)
2026-05-25 02:00 | WARP/keyboard-v2-redesign | migrate Telegram keyboard layer to keyboards_v2 (gap-filled to a behavior-preserving superset, all callback_data preserved), add 2-step preset tier flow + emergency progressive disclosure, archive legacy to _keyboards_archive; 1751 tests pass
2026-05-25 03:10 | WARP/portfolio-home-render-hotfix | fix pre-existing TypeError in bot/handlers/mvp/portfolio.py show_home — render_portfolio_home() called with unsupported today_trades/today_win_rate kwargs; caller aligned to renderer signature (no rendering change). AST scan of all handlers/mvp/*.py found no other render_* kwarg mismatches
2026-05-25 05:56 | WARP/ONA | fix gate 11 liquidity mismatch blocking all late_entry_v3 fills — _book_depth_usdc() computes CLOB bid depth; stored in SignalCandidate.metadata["clob_liquidity"]; _build_trade_signal uses it over near-zero DB liquidity_usdc for candle markets
2026-05-25 06:16 | WARP/ONA | codebase audit: C1 double-exposure dedup (pending_settlement), H1/H2 get_event_loop→get_running_loop, H3 copy-trade dedup, M1-M6 dead imports, M3 WalletWatcherUnavailable explicit catch, L1-L2 silent excepts → log
2026-05-25 07:02 | main | WARP-WPF: AutoTradePage.tsx preset list synced to backend — close_sweep selectable, safe_close/flip_hunter shown as SOON, stale presets removed
2026-05-25 08:19 | main | WARP-MDC: exit_watcher uses CLOB /midpoint as primary price source; rate limiters on Gamma (5 RPS) + CLOB reads (10 RPS); 4 demo positions voided
2026-05-25 12:30 | WARP/auth-password-byte-limit | fix Sentry DAWN-SNOWFLAKE-1729-26: ValueError password >72 bytes — added byte-length guard before all bcrypt call sites in webtrader/backend/auth.py (register/login/link_email)
2026-05-26 22:00 | claude/zealous-brahmagupta-LZaZV | lane #4: user daily $-loss override exposure + user max drawdown % halt gate + exit_price 0.0 display bugfix
2026-05-27 00:00 | WARP/R00T-webtrader-wallet | WebTrader wallet withdraw: POST /wallet/withdraw + 3-step WithdrawModal (amount→address→confirm) + api.requestWithdrawal wired
2026-05-27 00:30 | WARP/copy-task-repo-returning-fix | fix F-HIGH-2: create_task/update_task RETURNING missing 4 migration-035 columns → KeyError → copy task creation always failed silently
2026-05-27 01:00 | WARP/withdraw-onchain-skeleton | on-chain withdraw skeleton: _attempt_onchain_transfer() behind EXECUTION_PATH_VALIDATED guard; paper deferred, live raises NotImplementedError until polygon_usdc wired
2026-05-27 02:00 | WARP/migration-058-fk-fix | fix migration 058: drop copy_trade_events_copy_target_id_fkey before DROP TABLE copy_targets (applied to Supabase prod; both tables empty, 0 data impact)
2026-05-27 02:15 | WARP/fix-portfolio-withdraw-modal-props | fix fly deploy build break: PortfolioPage.tsx WithdrawModal missing onWithdraw/onSuccess props (TS2741); npm run build clean
2026-05-27 06:40 | WARP/webtrader-alert-persist-sort | WebTrader: persist dismissed alerts to localStorage (read alerts stop reappearing); /positions ORDER BY COALESCE(closed_at, opened_at) DESC + All-tab sort aligned (newest-closed on top)
2026-05-27 07:10 | WARP/webtrader-trade-strategy-label | WebTrader: surface positions.strategy_type on open/closed trade cards (API field + meta chip + Strategy detail row)
2026-05-27 07:30 | WARP/trade-strategy-preset-names | WebTrader trade cards: map strategy_type → preset display name (late_entry_v3 → "Close Sweep", etc.) per owner request
2026-05-26 23:04 | WARP/telegram-ux-v2 | Telegram MVP UI: HTML → MarkdownV2 (ui/tree.py + messages_mvp.py + _send.py); render_positions_empty() added; dead if-False removed
2026-05-26 23:40 | WARP/telegram-legacy-markdownv2 | Legacy wallet + emergency screens HTML → MarkdownV2 (messages.py 10 fns + wallet.py + emergency.py); admin_withdrawal_item_text kept HTML (operator path)
2026-05-27 05:40 | WARP/ROOT/notification-strategy-labels | Fix 3 runtime bugs: Telegram strategy labels (late_entry_v3→Close Sweep); WebTrader OPEN tab includes pending_settlement; Dashboard today_trades always-0
