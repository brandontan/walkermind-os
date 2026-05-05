# CrusaderBot -- WORKTODO

**Project:** projects/polymarket/crusaderbot
**Last Updated:** 2026-05-05 18:45 Asia/Jakarta

---

## Right Now

Active lane: P3b copy-trade strategy -- PR #877 open, MAJOR tier, SENTINEL pending (Issue #878, label: agent:sentinel).
Migration runner path: 008 fix in flight on WARP/CRUSADERBOT-FIX-MIGRATION-PATH (MINOR, awaiting WARP🔹CMD merge). 009 follow-up still required on PR #877 branch before SENTINEL.

---

## Phase 3 -- Strategy Plane

- [x] P3a -- Strategy Registry Foundation -- MERGED PR #876 (2026-05-05), STANDARD, FOUNDATION
- [ ] P3b -- Copy Trade strategy -- IN PROGRESS: PR #877 open, MAJOR, SENTINEL pending Issue #878
  - PRE-SENTINEL FIX: rebase PR #877 and git mv 009_copy_trade.sql from infra/migrations/ to migrations/ (008 already fixed on WARP/CRUSADERBOT-FIX-MIGRATION-PATH)
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
- [ ] R12d -- Live Opt-In Checklist -- NOT STARTED (MAJOR -- hard gate before EXE)
- [ ] R12e -- Live to Paper Auto-Fallback -- NOT STARTED (MAJOR)
- [ ] R12f -- Daily P&L Summary -- NOT STARTED (STANDARD)
- [ ] R12 -- Deployment (Fly.io) final -- NOT STARTED (MAJOR -- blocked on P3 complete + all R12 done + activation guards reviewed)

Done condition: All R12 lanes merged + activation guards reviewed by WARP🔸CMD before final deployment.

---

## Activation Guards (DO NOT TOUCH until explicit owner decision)

- EXECUTION_PATH_VALIDATED -- NOT SET
- CAPITAL_MODE_CONFIRMED -- NOT SET
- ENABLE_LIVE_TRADING -- NOT SET

---

## Known Issues / Tech Debt

- [ ] Migration runner path 009: 009_copy_trade.sql still at infra/migrations/ on PR #877 branch -- must be moved to migrations/ before P3b SENTINEL/merge (008 fixed on WARP/CRUSADERBOT-FIX-MIGRATION-PATH)
- [ ] F401 unused imports: bot/dispatcher.py, bot/handlers/dashboard.py, cache.py, config.py, domain/risk/gate.py, scheduler.py (ruff cleanup, LOW)
- [ ] check_alchemy_ws TCP-only, no full WS handshake (follow-up lane, LOW)
- [ ] services/* dead code (post-R12 cleanup, LOW)
- [ ] /deposit no tier gate (intentional, non-blocking)
