# CrusaderBot -- WORKTODO

**Project:** projects/polymarket/crusaderbot
**Last Updated: 2026-05-13 12:20 WIB

---

## Right Now
- Telegram UX v3 MERGED PR #1024 (2026-05-13). 7-button menu, dashboard v3, signals tap-hub, portfolio screen, nav_row, notifications utility.
- [x] Telegram UX v3 MERGED PR #1024 — 7-button menu, dashboard v3, signals tap-hub, nav_row, notifications utility

- GitHub queue synced: open PRs = 0, open issues = 0.
- Focus remains closed beta observation and paper-mode runtime monitoring.
- Production posture unchanged: Telegram + Fly.io live, PAPER ONLY; activation guards remain NOT SET.


- Signal Scan Engine MERGED PR #991 (2026-05-12). market_signal_scanner (60s), hourly_report cron, /health operator command, migration 024 deployed.
- Hotfix /insights strategy_type MERGED PR #995 (2026-05-12). weekly_insights signal breakdown now joins orders for strategy_type.
- Activation guards remain NOT SET.
- Production remains Telegram + Fly.io live, PAPER ONLY. signal_publications now being written by scanner.
- NEXT: closed beta observation / paper-mode runtime monitoring. WARP Auto Gate v1 MERGED PR #996 (2026-05-12).

---

## Fast Track Week 2 -- Live Gate + Premium UX

- [x] Premium PNL Insights UX -- MERGED PR #965 (2026-05-11), STANDARD, NARROW INTEGRATION. /insights command; insight_kb; dashboard:insights sub; my_trades nav update; 22 hermetic tests green; issue #963 closed.
- [x] Track F -- Live Opt-In Gate -- MERGED PR #970 (2026-05-12). 3-step /enable_live gate; 4-guard check; mode_change_events audit (021); auto-fallback 60s monitor; 20 hermetic tests green; issue #968 closed.
- [x] Track G -- UI Premium Pack 1 -- MERGED PR #989 (2026-05-12), STANDARD, PRESENTATION. UX overhaul/premium grade merged with 45 hermetic tests green.
- [x] Track H -- Portfolio Charts + Insights -- MERGED PR #979 (2026-05-12), STANDARD, NARROW INTEGRATION. /chart PNG photo; chart callbacks; /insights weekly breakdown; 30 hermetic tests green.
- [x] Track I -- Referral + Share System -- built and tracked in state; activation remains gated. Fee collection and referral payout remain OFF.
- [x] Hotfix /insights strategy_type -- MERGED PR #995 (2026-05-12). Fixes DAWN-SNOWFLAKE-1729-10 and DAWN-SNOWFLAKE-1729-Z.

Done condition: WARP🔹CMD merge decision on each lane; activation guards remain OFF throughout.

---

## Fast Track Week 1 -- Core Trading Loop

- [x] Track A -- Trade Engine + TP/SL worker -- MERGED PR #942 (2026-05-11), MAJOR, FULL RUNTIME INTEGRATION. TradeEngine service layer; signal_scan_job routes through TradeEngine; 47 hermetic tests green.
- [x] Track B -- Copy Trade Execution -- MERGED PR #948 (2026-05-11), MAJOR. CopyTradeMonitor.run_once(), 020 migration, 25 hermetic tests green; P1 fixes applied.
- [x] Track C -- Trade Notifications -- MERGED PR #951 (2026-05-11), STANDARD. TradeNotifier service layer; 16 hermetic tests green; already_closed guard P2 fix.
- [x] Track D -- Live Gate Hardening -- MERGED PR #954 (2026-05-11), MAJOR. WARP•SENTINEL APPROVED 92/100; 35 tests green.
- [x] Track E -- Daily P&L Report -- MERGED PR #962 (2026-05-11), STANDARD, NARROW INTEGRATION. Paper-mode daily Telegram P&L summary; 26 daily_pnl_summary tests green; issue #960 closed.

Done condition: Track A-E merged and SENTINEL-approved where MAJOR; activation guards remain OFF.

---

## Phase 3 -- Strategy Plane

- [x] P3a -- Strategy Registry Foundation -- MERGED PR #876 (2026-05-05), STANDARD, FOUNDATION.
- [x] P3b -- Copy Trade strategy -- MERGED PR #877 (2026-05-06), MAJOR, SENTINEL CONDITIONAL resolved.
- [x] P3c -- Signal Following strategy -- MERGED PR #892, MAJOR, SENTINEL APPROVED 100/100.
- [x] P3d -- Per-user signal scan loop + execution queue wiring -- MERGED PR #897 + state sync PR #898, MAJOR, SENTINEL APPROVED 94/100.
- [x] P3e -- MomentumReversalStrategy adapter -- MERGED PR #978 (2026-05-11), STANDARD, NARROW INTEGRATION.

Done condition: P3 lanes merged, registry catalog populated at boot, scan loop wired through risk gate, SENTINEL approved before live activation.

---

## R12 -- Production Readiness

- [x] R12a -- CI/CD Pipeline (GitHub Actions) -- DONE (PR #855 merged 2026-05-04, STANDARD).
- [x] R12b -- Fly.io Health Alerts -- DONE (PR #856 merged).
- [x] R12c -- Auto-Close / Take-Profit -- DONE (PR #865 merged 2026-05-05, MAJOR, SENTINEL APPROVED 95/100).
- [x] R12d -- Telegram Position UX -- DONE (PR #868 merged).
- [x] R12e -- Auto-Redeem System -- DONE (PR #869 merged, MAJOR; conditions resolved PR #879).
- [x] R12f -- Operator Dashboard + Kill Switch + Job Monitor -- DONE (PR #874 merged, STANDARD).
- [x] R12 Live Readiness -- Live Opt-In Checklist / Auto-Fallback / Daily P&L Summary -- DONE on WARP/CRUSADERBOT-R12-LIVE-READINESS.
- [ ] R12 -- Deployment final operator verification pending per runbooks. Activation guards remain NOT SET.

---

## Activation Guards (DO NOT TOUCH until explicit owner decision)

- EXECUTION_PATH_VALIDATED -- NOT SET
- CAPITAL_MODE_CONFIRMED -- NOT SET
- ENABLE_LIVE_TRADING -- NOT SET
- RISK_CONTROLS_VALIDATED -- NOT SET
- USE_REAL_CLOB -- NOT SET (default False, paper-safe)

---

## Known Issues / Tech Debt

- [x] WARP Auto Gate v1 issue #980 -- STANDARD repo automation lane, no CrusaderBot runtime code. MERGED PR #996 (2026-05-12).
- [ ] check_alchemy_ws TCP-only, no full WS handshake (follow-up lane, LOW).
- [ ] services/* dead code (post-R12 cleanup, LOW).
- [ ] /deposit no tier gate (intentional, non-blocking).
- [ ] WARP/LIB-F401-CLEANUP (MINOR, deferred post-demo) -- shared-lib cross-project audit required before cleanup.

