# CrusaderBot -- WORKTODO

**Project:** projects/polymarket/crusaderbot
**Last Updated:** 2026-05-11 21:45

---

## Right Now

- Track E Daily P&L Report MERGED PR #962; issue #960 closed. Week 1 Fast Track Tracks A-E complete.
- Week 2 first lane: Premium PNL Insights UX (issue #963) MERGED PR #965 (2026-05-11). Week 2 next lane TBD by WARP🔹CMD.
- Activation guards remain NOT SET.
- Production remains Telegram + Fly.io live, PAPER ONLY.

---

## Fast Track Week 2 -- Live Gate + Premium UX

- [x] Premium PNL Insights UX -- PR open WARP/crusaderbot-premium-pnl-insights (2026-05-11), STANDARD, NARROW INTEGRATION. /insights command; insight_kb; dashboard:insights sub; my_trades nav update; 22 hermetic tests green; issue #963.
- [ ] Live gate preparation (SENTINEL + owner checklist) -- NOT STARTED.
- [ ] Referral / fee / fee prep -- NOT STARTED.

Done condition: WARP🔹CMD merge decision on each lane; activation guards remain OFF throughout.

---

## Fast Track Week 1 -- Core Trading Loop

- [x] Track A -- Trade Engine + TP/SL worker -- MERGED PR #942 (2026-05-11), MAJOR, FULL RUNTIME INTEGRATION. TradeEngine service layer; signal_scan_job routes through TradeEngine; 47 hermetic tests green.
- [x] Track B -- Copy Trade Execution -- MERGED PR #948 (2026-05-11), MAJOR. CopyTradeMonitor.run_once(), 020 migration, 25 hermetic tests green; P1 fixes applied.
- [x] Track C -- Trade Notifications -- MERGED PR #951 (2026-05-11), STANDARD. TradeNotifier service layer; 16 hermetic tests green; already_closed guard P2 fix.
- [x] Track D -- Live Gate Hardening -- MERGED PR #954 (2026-05-11), MAJOR. Gate step 14 slippage/market-impact, risk assertion audit, shadow/live parity hooks, readiness validator, RISK_CONTROLS_VALIDATED default false; WARP•SENTINEL APPROVED 92/100; 35 tests green.
- [x] Track E -- Daily P&L Report -- MERGED PR #962 (2026-05-11), STANDARD, NARROW INTEGRATION. Paper-mode daily Telegram P&L summary; opened/closed/W/L counts; no-trade empty state; scheduler callback wiring; 26 daily_pnl_summary tests green; issue #960 closed.

Done condition: Track A-E merged and SENTINEL-approved where MAJOR; activation guards remain OFF; Week 2 queued next.

---

## Phase 3 -- Strategy Plane

- [x] P3a -- Strategy Registry Foundation -- MERGED PR #876 (2026-05-05), STANDARD, FOUNDATION
- [x] P3b -- Copy Trade strategy -- MERGED PR #877 (2026-05-06) a369129d, MAJOR, SENTINEL CONDITIONAL 71/100 resolved
  - Migration runner path fix: PR #881 MERGED (2026-05-06) 538fd999 -- 008+009 now in migrations/
- [x] P3c -- Signal Following strategy -- MERGED PR #892 (5ee8487e), MAJOR, SENTINEL APPROVED 100/100
- [x] P3d -- Per-user signal scan loop + execution queue wiring -- MERGED PR #897 (bb08092) + state sync PR #898 (7bb0487f), MAJOR, SENTINEL APPROVED 94/100. 464/464 tests green.

Done condition: P3a-P3d merged, registry catalog populated at boot, scan loop wired through risk gate, SENTINEL APPROVED before live activation.

---

## R12 -- Production Readiness

- [x] R12a -- CI/CD Pipeline (GitHub Actions) -- DONE (PR #855 merged 2026-05-04, STANDARD)
- [x] R12b -- Fly.io Health Alerts -- DONE (PR #856 merged)
- [x] R12c -- Auto-Close / Take-Profit -- DONE (PR #865 merged 2026-05-05, MAJOR, SENTINEL APPROVED 95/100)
- [x] R12d -- Telegram Position UX (live monitor + per-position force close) -- DONE (PR #868 merged)
- [x] R12e -- Auto-Redeem System -- DONE (PR #869 merged, MAJOR, SENTINEL CONDITIONAL 64/100 -- conditions resolved PR #879)
- [x] R12f -- Operator Dashboard + Kill Switch + Job Monitor -- DONE (PR #874 merged 2026-05-05, STANDARD)
- [x] R12 Live Readiness -- Live Opt-In Checklist (8 gates + audit + /live_checklist + CONFIRM dialog) -- DONE on WARP/CRUSADERBOT-R12-LIVE-READINESS (STANDARD, NARROW INTEGRATION)
- [x] R12 Live Readiness -- Live to Paper Auto-Fallback (router + risk gate + kill switch lock cascade) -- DONE on WARP/CRUSADERBOT-R12-LIVE-READINESS (STANDARD, NARROW INTEGRATION)
- [x] R12 Live Readiness -- Daily P&L Summary (cron 23:00 Jakarta + /summary_on /summary_off) -- DONE on WARP/CRUSADERBOT-R12-LIVE-READINESS (STANDARD, NARROW INTEGRATION)
- [ ] R12 -- Deployment (Fly.io) final -- Lane 1B MERGED PR #901 (MAJOR, NARROW INTEGRATION, SENTINEL APPROVED 95/100). Lane 2C MERGED PR #907 (Telegram demo polish, CRU-6, MINOR, Claim NONE). Lane 1C MERGED PR #908 (2026-05-08) ca5f6f57 (STANDARD, NARROW INTEGRATION, SENTINEL APPROVED 98/100) -- migration 014 + seed/cleanup scripts + runbook, 514/514 tests green at merge. Operator prod verification pending per runbooks (Issue #900). Activation guards remain NOT SET.

Done condition: All R12 lanes merged + activation guards reviewed by WARP🔹CMD before final deployment.

---

## Activation Guards (DO NOT TOUCH until explicit owner decision)

- EXECUTION_PATH_VALIDATED -- NOT SET
- CAPITAL_MODE_CONFIRMED -- NOT SET
- ENABLE_LIVE_TRADING -- NOT SET
- RISK_CONTROLS_VALIDATED -- NOT SET
- USE_REAL_CLOB -- NOT SET (default False, paper-safe)

---

## Known Issues / Tech Debt

- [x] F401 unused imports: bot/dispatcher.py, bot/handlers/dashboard.py, cache.py, config.py, domain/risk/gate.py, scheduler.py, services/signal_scan/signal_scan_job.py -- DONE on WARP/CRUSADERBOT-PREFLIGHT-CLEANUP
- [ ] check_alchemy_ws TCP-only, no full WS handshake (follow-up lane, LOW)
- [ ] services/* dead code (post-R12 cleanup, LOW)
- [ ] /deposit no tier gate (intentional, non-blocking)
- [x] MIN-01 P3b: user_id type annotations on 3 copy_trade handler helpers -- DONE on WARP/CRUSADERBOT-PREFLIGHT-CLEANUP
- [x] MIN-02 P3b: phase comment in dispatcher.py -- DONE on WARP/CRUSADERBOT-PREFLIGHT-CLEANUP
- [x] MIN-03 P3b: copy_trade_events.copy_target_id nullable FK (migration 013, ON DELETE CASCADE -> ON DELETE SET NULL -- persistence behaviour change; lane reclassified STANDARD/NARROW INTEGRATION) -- DONE on WARP/CRUSADERBOT-PREFLIGHT-CLEANUP (PR #899)
- [ ] WARP/LIB-F401-CLEANUP (MINOR, deferred post-demo) -- 5 pre-existing F401 occurrences in shared-library code surfaced by Codex on PR #899: lib/strategies/logic_arb.py:42 (get_no_price), lib/strategies/value_investor.py:30 (get_no_price), lib/strategies/weather_arb.py:25 (json), lib/strategies/weather_arb.py:29 (urllib.request), lib/strategy_base.py:34 (field). Cross-project audit required before cleanup -- lib/ is shared with other projects (WARP-CodX, future tenants).
