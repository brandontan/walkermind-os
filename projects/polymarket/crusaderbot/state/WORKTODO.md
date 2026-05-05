# CrusaderBot -- WORKTODO

**Project:** projects/polymarket/crusaderbot
**Last Updated:** 2026-05-06 05:01 Asia/Jakarta

---

## Right Now

- R12 Live Readiness batch (live opt-in checklist + live-to-paper fallback + daily P&L summary) submitted on WARP/CRUSADERBOT-R12-LIVE-READINESS. STANDARD, NARROW INTEGRATION. Awaiting WARP🔹CMD review.
- After merge: P3c -- Signal Following strategy.

---

## Phase 3 -- Strategy Plane

- [x] P3a -- Strategy Registry Foundation -- MERGED PR #876 (2026-05-05), STANDARD, FOUNDATION
- [x] P3b -- Copy Trade strategy -- MERGED PR #877 (2026-05-06) a369129d, MAJOR, SENTINEL CONDITIONAL 71/100 resolved
  - Migration runner path fix: PR #881 MERGED (2026-05-06) 538fd999 — 008+009 now in migrations/
- [ ] P3c -- Signal Following strategy -- NOT STARTED (MAJOR)
- [ ] P3d -- Per-user signal scan loop + execution queue wiring -- NOT STARTED (MAJOR -- wires registry into risk gate)

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
- [ ] R12 -- Deployment (Fly.io) final -- NOT STARTED (MAJOR -- blocked on P3c/P3d + activation guards reviewed)

Done condition: All R12 lanes merged + activation guards reviewed by WARP🔹CMD before final deployment.

---

## Activation Guards (DO NOT TOUCH until explicit owner decision)

- EXECUTION_PATH_VALIDATED -- NOT SET
- CAPITAL_MODE_CONFIRMED -- NOT SET
- ENABLE_LIVE_TRADING -- NOT SET

---

## Known Issues / Tech Debt

- [ ] F401 unused imports: bot/dispatcher.py, bot/handlers/dashboard.py, cache.py, config.py, domain/risk/gate.py, scheduler.py (ruff cleanup, LOW)
- [ ] check_alchemy_ws TCP-only, no full WS handshake (follow-up lane, LOW)
- [ ] services/* dead code (post-R12 cleanup, LOW)
- [ ] /deposit no tier gate (intentional, non-blocking)
- [ ] MIN-01 P3b: user_id type annotations missing in 3 copy_trade handler helpers (deferred)
- [ ] MIN-02 P3b: phase comment in dispatcher.py (deferred)
- [ ] MIN-03 P3b: copy_trade_events.copy_target_id nullable FK (deferred)
