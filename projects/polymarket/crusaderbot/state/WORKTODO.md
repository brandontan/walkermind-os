# CrusaderBot — FINISHING WORKTODO

**Project:** projects/polymarket/crusaderbot
**Last Updated : 2026-05-28 23:45

> North Star: **finish CrusaderBot as a trusted, Telegram-first, multi-user, PAPER-mode autonomous trading bot.**
> No feature creep. Runtime truth > cosmetics.

---

## P0 -- Runtime Spine Validation (MANDATORY)

Prove the actual runtime spine is real end-to-end:


```text
/start
→ onboarding
↓ user state
↓ paper wallet
− default strategy
− active scanner
"钒 analysis engine
↓ risk gate
−  paper trade open
↓ position monitor
↓ paper trade close
↓ portfolio update
↓ Telegram receipt
```

Deliverables:
- [x] Runtime evidence matrix
- [x] Broken/fake/dead path map
- [x] Multi-user isolation verification
- [x] Proof PAPER ONLY posture unchanged
- [x] Pre-handoff CORE AUDIT — WARP/crusaderbot-system-audit 2026-05-23 (sentinel report; F-CRIT-1 boot-blocker found)
- [x] F-CRIT-1 boot fix — bot/ui/__init__.py stale BAR/BRANCH/LAST re-export removed; import clean + 1613 pytest pass (consolidated into PR #1294, per WARP🔹CMD; PR #1295 closed)
- [ ] F-HIGH-2 — 0 live trade data; PRIMARY cause fixed in WARP/lib-strategy-load-fix (lib/ strategies never loaded: outside Docker build context + relative-import loader bug; now vendored + importable, all 7 load). Pending SENTINEL + deploy to confirm trades flow. SECONDARY (open): Phase C evaluate_publications_for_user feed-eval path.

---

## P0 -- WebTrader Realtime Trust

Validate and fix realtime trust gaps:

- [x] Terminal updates without manual refresh
- [x] Scanner counts match backend jobs
- [x] Recent Activity synced to runtime truth
- [x] Portfolio / Wallet sync with ledger
- [x] Heartbeat / last_tick / last_scan timestamps
- [x] PAPER ONLY posture clear; LIVE not misleading

---

## P0 -- Production Integrity

Close production gaps before beta:

- [x] Apply migrations 027/029/030 — APPLIED 2026-05-21
- [x] Apply migration 031 — APPLIED 2026-05-21
- [x] Apply migration 044 (DROP access_tier) — CONFIRMED APPLIED (access_tier column gone from schema)
- [x] Fly.io deploy validation
- [x] Scheduler health / retry check
- [x] RLS lockout — Row Level Security ENABLED on ALL 43/43 public tables (migration 046 + later migs incl. 055 scan_runs; verified live 2026-05-27 via Supabase advisors + list_tables — 0 rls_disabled errors).
- [x] WARP-52 — portfolio_snapshots Python writer / cb_portfolio NOTIFY wiring (Issue #1245) [STANDARD] — DELIVERED WARP/portfolio-snapshots-writer 2026-05-21
- [x] Telegram notification reliability — WARP-53 DELIVERED 2026-05-21 (WARP/warp53-reliability-hardening)
- [x] Logging and operational sanity

---

## P1 -- Closed Beta Hardening

Observe the runtime under real usage:

- [x] No duplicate trades — WARP-54 DELIVERED 2026-05-21 (paper.execute ON CONFLICT pinned + regression test)

---

## P1 -- Telegram UX Final (After Runtime Proven)

- [x] No dead buttons
- [x] No fake placeholder routes
- [x] State-driven keyboard
- [x] Concierge onboarding polish
- [x] Portfolio / Settings clarity
- [x] No legacy tier / operator wording

---

## P2 -- Project Finish Criteria

CRUSADERBOT is considered **DONE** only when:

- [x] WebTrader running
- [x] Runtime spine proven end-to-end
- [x] WebTrader realtime trusted
- [x] Telegram stable
- [x] Paper trading stable
- [x] No user bleed
- [x] No dead routes
- [x] Closed beta clean
- [ ] Production checklist complete

---

## Active — In Progress

- [x] WARP•R00T safe_close + flip_hunter Kreo-parity [MAJOR/NARROW] — WARP/ROOT/safe-close-flip-hunter-kreo-parity. Realigns the two candle presets to Kreo's reference behaviour (per Kreo Polymarket Telegram bot docs): safe_close min_ask_diff 0.08→0.01 + new force-exit at rem=30s (closes BEFORE the noisy final 30s where SL was firing at random); flip_hunter inverted from late-window underdog to early-window favored side (Kreo "With Trend") with per-timeframe windows (5m rem 160-300 / 15m rem 480-900) + force-exit at end of entry window. Adds Kreo-style fixed-time exit MECHANISM in late_entry_v3.evaluate_exit (checks force-exit before flip-stop), single-source-of-truth `force_exit_at_rem_sec_for(preset, tf)` helper consumed by both entry + exit paths, per-tf-aware `_resolve_preset_params(preset, tf)` resolver, OpenPositionForExit + exit_watcher enrichment to pass active_preset + selected_timeframe + seconds_to_close (from existing JOIN + resolution_at — no migration). close_sweep unchanged. 27 new hermetic tests; suite 1894 pass. Risk gate + activation guards untouched. Report: reports/forge/safe-close-flip-hunter-kreo-parity.md.
- [x] WARP•R00T late-entry fill-drift guard [STANDARD/NARROW] — WARP/ROOT/late-entry-fill-drift-guard. Closes a fill-time correctness gap in close_sweep / safe_close / flip_hunter: late_entry_v3 candidates passed scan-time gates with one set of orderbook prices, then `_process_candidate` fetched the live fill price via `get_live_market_price` and built the TradeSignal with no re-validation. Candle markets drift 0.10+ in seconds, so actual fills landed wherever — prod 24h showed only 5.5% of safe_close trades + 17% of close_sweep trades inside the strategy's intended band (avg entry 0.45, with fills as low as 0.04 and as high as 0.94). Fix: `late_entry_v3._evaluate_market` now emits `fav_price_min/max` in candidate metadata; new gate 3c in `_process_candidate` (between live-price fetch and signal build) requires `live_fill_price ∈ [fav_price_min, fav_price_max)` — skipped_fill_drifted otherwise. Metadata-driven and opt-in: signal_following / lib / confluence_scalper candidates carry no band keys → gate no-ops. Risk gate's 13 steps + activation guards untouched. 6 new hermetic tests (4 gate-3c + 2 strategy-metadata); full suite 1866 pass; ruff + py_compile clean. Report: reports/forge/late-entry-fill-drift-guard.md.
- [x] WARP•R00T LIVE+PAPER readiness pass — Lane 1 system-ready-audit [MINOR/FOUNDATION] MERGED #1409. Read-only audit. Verdict: 0 current risks. All 5 LIVE activation guards default false, assert_live_guards 8-condition chain, router GUARD_BYPASS_ATTEMPT logging + paper-fallback, LIVE-flip 8-gate checklist + typed CONFIRM, PAPER-default at schema layer across all three new-user paths verified. Surfaced 3 brittleness items for Lane 2. Report: reports/forge/system-ready-audit.md.
- [x] WARP•R00T LIVE+PAPER readiness pass — Lane 2 paper-default-hardening [STANDARD/NARROW] MERGED #1410. Belt-and-suspenders: explicit `trading_mode='paper'` in every user_settings INSERT (users.py upsert_user + lazy get_settings_for + new explicit INSERT in webtrader/backend/auth.py signup); silent `except Exception: pass` in webtrader signup replaced with logger.exception; new hermetic tests/test_paper_default_invariant.py (5 tests, INSERT-call-shape + source-regex layers). Full suite 1859 pass; ruff + py_compile clean. PAPER remains the only mode any user receives at creation regardless of ENABLE_LIVE_TRADING. Report: reports/forge/paper-default-hardening.md.
- [x] WARP•R00T LIVE+PAPER readiness pass — Lane 3 live-readiness-final [MINOR] MERGED #1411. State-doc sync only. Updates LIVE_READINESS.md, PRODUCTION_CHECKLIST.md, WORKTODO.md, PROJECT_STATE.md, CHANGELOG.md to reflect Lanes 1+2 closure; owner-only "Final go-live sequence" preserved verbatim. Report: reports/forge/live-readiness-final.md.
- [x] WARP•R00T README/WARP•R00T surface refresh [MINOR] MERGED #1412. Added `Engineering: Live Ready` badge + "Operating Posture" section (PAPER-only production / LIVE-ready engineering + 5 activation-guard names + link to LIVE_READINESS.md); WARP•R00T added to System Architecture diagram + Authority Chain table; Branch Naming section documents `WARP/{feature}` + `WARP/ROOT/{feature}` with explicit ban on auto-generated `claude/*` branches. Doc-only — README.md changes; no code touched.
- [x] WARP•R00T public-ready audit [MAJOR/FOUNDATION] — WARP/ROOT/public-ready-hardening. Paper-safe core verified; privacy-policy.md fixed. Report: reports/forge/public-ready-hardening.md.
- [x] H2 — inbound rate limiting / abuse control for public API + bot surfaces [STANDARD] — DELIVERED WARP/ROOT/api-rate-limit. RateLimitMiddleware (per-IP sliding window, 120rpm/60s, 429+Retry-After, health/webhook exempt); 6 tests; suite 1798 pass. Report: reports/forge/api-rate-limit.md.
- [x] H1 — ops auth hardening: token-out-of-URL via cookie session (api/ops.py) [MAJOR — SENTINEL] — DELIVERED WARP/ROOT/ops-auth-cookie. POST /ops/login → HttpOnly+Secure+SameSite=Lax cookie (HMAC of OPS_SECRET); GET gated to login form when unauthed; mutators accept cookie/header/legacy-token (no lockout); rotation via OPS_SECRET change. 48 ops tests pass; suite 1808. SENTINEL gate recommended before merge. (Per-operator named accounts not in scope — single shared secret retained.)
- [x] M1 — enable RLS on the last remaining public table [MAJOR-adjacent]. DONE — verified 2026-05-27: 43/43 public tables rls_enabled=true (Supabase list_tables); 0 rls_disabled_in_public advisor errors. Closed by migration 046 + later migs (incl. 055 scan_runs); no new migration needed.
- [x] M3 — check_alchemy_ws full WS handshake (monitoring/health.py) [STANDARD] — DONE WARP/ROOT/alchemy-ws-handshake. Real WS handshake + eth_blockNumber probe replaces TCP-only check; fails on broken WS. 4 hermetic tests; test_health.py 42 pass. Report: reports/forge/alchemy-ws-handshake.md.
- [ ] C1 — wire on-chain capital movement (withdraw/redeem/sweep) [MAJOR — owner decision + SENTINEL + staged]. LIVE blocker: wallet/withdrawals.py:158 raises NotImplementedError. Done when live fund flows execute safely behind the guard sequence. DO NOT start without explicit WARP🔹CMD go.

- [x] WARP-TDC — Trade diversity + concurrency [MAJOR] — MERGED (verified in main 2026-05-26: signal_evaluator._diversify_order present; PROFILES max_concurrent = 5/12/20, custom 12). Fixed beta #1 "same ~5 trades": (A) _diversify_order orders each user's candidates by sha1(user_id:market_id); (B) caps raised 3/5/5 -> 5/12/20, fixed fences (Kelly 0.25 / 10% pos / -$2k / 8% dd / 40% exposure) untouched. Lane 1 (categories) + Lane 3 (edge model) also in main.
- [x] LANE-1 — Category mapping fix [STANDARD] — integrations/polymarket.py: new get_events_with_markets() fetches Gamma /events endpoint + annotates each market dict with category from event tags (e.g. "crypto finance sports"); signal_scan_job._fetch_markets_for_lib_strategies() now calls get_events_with_markets() instead of get_markets(); _filter_markets_by_category() unchanged — now works correctly because category field is populated. 14 new hermetic tests in test_category_mapping.py. py_compile clean. Report: projects/polymarket/crusaderbot/reports/forge/category-mapping.md. STANDARD, WARP🔹CMD review.
- [x] LANE-3 — Edge-model momentum fix [STANDARD] — config.py SCANNER_EDGE_MIN_PRICE 0.05->0.15, SCANNER_EDGE_MAX_PRICE 0.95->0.85; market_signal_scanner.py edge formula replaced: abs(yes_p-0.5) -> max(|1d_change|,|1h_change|×1.5) (eliminates systematic longshot bias); side logic replaced: mean-reversion -> momentum-following (YES if recent_change≥0); 5 existing tests updated + 5 new tests (longshot rejection, near-fair momentum pass, 1h>1d preference). py_compile clean. Report: projects/polymarket/crusaderbot/reports/forge/edge-model-momentum.md. STANDARD, WARP🔹CMD review.
- [x] WARP-RMS — Real-market settlement fix [MAJOR] — MERGED PR #1314 + deployed; feed migration done (6 users Demo->Live). FIX1 polymarket.get_market() 422-on-hex-conditionId (path segment -> ?conditionId= query) that silently blocked ALL resolution/settlement -> slots never freed; FIX2 scanner edge-finder now publishes real markets to the LIVE feed with is_demo=FALSE by default (SCANNER_DEMO_FEED_ENABLED gate for tests/dev); FIX3 pending_settlement status (never flat-close on expiry, counted in exposure, settles on official close). 18+13+62 tests green. Optional owner action: manual void/clear of leftover demo positions.
- [x] WARP-61 — WebTrader confluence_scalper exposure (issue #1269) [STANDARD] — MERGED 7cbd8b814533
- [x] WARP-60 — ConfluenceScalperStrategy (issue #1267) [STANDARD] — MERGED b3ec4b7d4930
- [x] WARP-59 — Copy Wallet end-to-end bridge: copy_targets → copy_trade_tasks (Issue #1265) [STANDARD] — DELIVERED WARP/warp59-copy-wallet-e2e-bridge 2026-05-21 (MVP write path realigned to canonical execution table read by services/copy_trade/monitor.py).
- [x] WARP-58 — Fix domain/signal/copy_trade.py copy_targets schema mismatch (Issue #1263) [STANDARD] — DELIVERED WARP/warp58-copy-trade-schema-fix 2026-05-21 (closes WARP-57 SENTINEL Round-1 read-path drift).
- [x] WARP-57 — Telegram UX MVP v1 Rebuild (Issue #1260) [MAJOR] — MERGED c6ae44b18572. SENTINEL CONDITIONAL APPROVED 92/100.

---

## Deferred / NOT NOW

❌ live trading activation
❌ fancy analytics expansion
❌ dashboard redesign
❌ monetization / premium expansion
❌ new feature creep until PAPER runtime is trusted
- [x] WARP-46 — Runtime Spine Validation (Issue #1243)
- [x] WARP-62 — P0: remove threading.Lock from registry.py → eager module-level init (issue #1273) [STANDARD] — DELIVERED WARP/warp62-63-fix 2026-05-22
- [x] WARP-63 — P1: migrate CopyTradeStrategy.scan() from copy_targets → copy_trade_tasks (issue #1274) [STANDARD] — DELIVERED WARP/warp62-63-fix 2026-05-22
- [x] WARP-64 — P0: fix CI pytest failures in test_warp59_copy_wallet_bridge.py (issue #1277) [STANDARD] — DELIVERED WARP/warp64-ci-fix 2026-05-22
- [x] WARP-65 — P1: fix Telegram UX persistent keyboard + bot status + strategy label (issue #1278) [STANDARD] — DELIVERED WARP/warp65-telegram-ux-fix 2026-05-22
- [x] WARP-66 — Telegram UX polish (issue #1282) [STANDARD] — MERGED ab6f397f2741
- [x] SENTINEL re-audit post WARP-62+63 (issue #1276) — APPROVED 96/100 — MERGED d42b7e915356
- [x] WARP-67 — Telegram UX final clean (issue #1284) [STANDARD] — MERGED 2989b7c6e788
- [x] WARP-68 — Structured card format + positions pagination (issue #1286) [STANDARD] — MERGED b7355541d496
- [x] WARP-69 — Full structured card format all 66 render functions (issue #1288) [STANDARD] — MERGED b50ef1a2ce86
- [x] WARP-70 — Dynamic Auto Trade capital = balance × risk fraction (issue #1290) [MINOR] — DELIVERED WARP/warp70-dynamic-capital 2026-05-22
- [x] WARP-71 — Premium terminal UI HTML parse mode [STANDARD] — MERGED e443c212c1e7
- [x] WARP-72 — Fix phantom dot + do_start capital from _read_state [MINOR] — 93d5709c0c5c
- [x] WARP-73 — Phantom dot fix + clean Telegram HTML format [MINOR hotfix] — 5364eb97 + 7bb7a69a + c8de0a5e
- [x] SENTINEL system audit pre-handoff — F-CRIT-1 RESOLVED, bot/ui/__init__.py fix — MERGED fa1bd2537650
- [x] WARP-1296 — RLS enable 42 tables anon-key lockout [MAJOR] SENTINEL 98/100 — MERGED 82f08af2a27b
- [x] F-HIGH-2 — vendor lib/ into crusaderbot package, fix prod strategy load [MAJOR] SENTINEL 99/100 — MERGED e235fa294823
