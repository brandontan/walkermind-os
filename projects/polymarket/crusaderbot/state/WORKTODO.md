# CrusaderBot — FINISHING WORKTODO

**Project:** projects/polymarket/crusaderbot
**Last Updated : 2026-05-22 22:30

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
- [ ] RLS lockout — enable Row Level Security on all 42 public tables (anon-key exposure); migration 046 drafted in WARP/rls-enable-anon-lockout, pending WARP🔹CMD review + apply
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

- [ ] WARP-TDC — Trade diversity + concurrency [MAJOR] — PR open (branch claude/crusaderbot-signal-scan-debug-Xnckj). Fixes beta #1 "same ~5 trades": (A) signal_evaluator._diversify_order orders each user's candidates by sha1(user_id:market_id) so subscribers stop converging on the identical published_at-ASC prefix (deterministic per user+market, single point covers both live consumers); (B) PROFILES max_concurrent 3/5/5 -> 5/12/20 (custom 12), fixed fences untouched, 40% exposure still bounds total. 6 new + 354 existing tests green. SENTINEL MAJOR pending. Lane 1 (categories) DONE — see below; Lane 3 (edge model) DONE — see below.
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
