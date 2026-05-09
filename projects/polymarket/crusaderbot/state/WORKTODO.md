# CrusaderBot -- WORKTODO

**Project:** projects/polymarket/crusaderbot
**Last Updated:** 2026-05-09 11:30 Asia/Jakarta

---

## Right Now

- Ops dashboard + Tier 2 operator seed — WARP/CRUSADERBOT-OPS-DASHBOARD-TIER2-FIX. Tier STANDARD / Claim NARROW INTEGRATION / SENTINEL NOT REQUIRED. New api/ops.py (GET /ops HTML + POST /ops/kill + POST /ops/resume), scripts/seed_operator_tier.py wired to fly.toml [deploy] release_command, kill-switch runbook refreshed for ADMIN_USER_IDS consumption. 42 new tests (17 seed + 25 ops). Ruff clean on changed files. Auth on /ops* deferred post-demo (in-code TODO). Awaiting WARP🔹CMD review + merge.
- Lane 1C (CRU-5) — Demo Data Seeding — PR #908 SENTINEL APPROVED 98/100. WARP/CRUSADERBOT-DEMO-SEED-DATA. Tier STANDARD / Claim NARROW INTEGRATION. Zero P0/P1, 4 P2 (3 doc-row 32→34 drifts, 1 docstring stub, 1 migration comment — all post-merge OK). All BLOCK criteria explicitly evaluated and not triggered. Ruff clean. Sentinel report: projects/polymarket/crusaderbot/reports/sentinel/demo-seed-data.md. Awaiting WARP🔹CMD merge decision. R12 Lane 1B MERGED PR #901. Lane 2C MERGED PR #907. Activation guards remain NOT SET.

---

## Phase 3 -- Strategy Plane

- [x] P3a -- Strategy Registry Foundation -- MERGED PR #876 (2026-05-05), STANDARD, FOUNDATION
- [x] P3b -- Copy Trade strategy -- MERGED PR #877 (2026-05-06) a369129d, MAJOR, SENTINEL CONDITIONAL 71/100 resolved
  - Migration runner path fix: PR #881 MERGED (2026-05-06) 538fd999 — 008+009 now in migrations/
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
- [ ] R12 -- Deployment (Fly.io) final -- Lane 1B MERGED PR #901 (MAJOR, NARROW INTEGRATION, SENTINEL APPROVED 95/100). Lane 2C MERGED PR #907 (Telegram demo polish, CRU-6, MINOR, Claim NONE). Lane 1C (demo data seeding, CRU-5) PR #908 SENTINEL APPROVED 98/100 on WARP/CRUSADERBOT-DEMO-SEED-DATA (STANDARD, NARROW INTEGRATION) — migration 014 + seed/cleanup scripts + runbook, 514/514 tests green, ruff clean, zero P0/P1, 4 P2 (post-merge OK), awaiting WARP🔹CMD merge decision. Operator prod verification pending per runbooks (Issue #900). Activation guards remain NOT SET.

Done condition: All R12 lanes merged + activation guards reviewed by WARP🔹CMD before final deployment.

---

## Activation Guards (DO NOT TOUCH until explicit owner decision)

- EXECUTION_PATH_VALIDATED -- NOT SET
- CAPITAL_MODE_CONFIRMED -- NOT SET
- ENABLE_LIVE_TRADING -- NOT SET

---

## Known Issues / Tech Debt

- [x] F401 unused imports: bot/dispatcher.py, bot/handlers/dashboard.py, cache.py, config.py, domain/risk/gate.py, scheduler.py, services/signal_scan/signal_scan_job.py — DONE on WARP/CRUSADERBOT-PREFLIGHT-CLEANUP
- [ ] check_alchemy_ws TCP-only, no full WS handshake (follow-up lane, LOW)
- [ ] services/* dead code (post-R12 cleanup, LOW)
- [ ] /deposit no tier gate (intentional, non-blocking)
- [x] MIN-01 P3b: user_id type annotations on 3 copy_trade handler helpers — DONE on WARP/CRUSADERBOT-PREFLIGHT-CLEANUP
- [x] MIN-02 P3b: phase comment in dispatcher.py — DONE on WARP/CRUSADERBOT-PREFLIGHT-CLEANUP
- [x] MIN-03 P3b: copy_trade_events.copy_target_id nullable FK (migration 013, ON DELETE CASCADE → ON DELETE SET NULL — persistence behaviour change; lane reclassified STANDARD/NARROW INTEGRATION) — DONE on WARP/CRUSADERBOT-PREFLIGHT-CLEANUP (PR #899)
- [ ] WARP/LIB-F401-CLEANUP (MINOR, deferred post-demo) — 5 pre-existing F401 occurrences in shared-library code surfaced by Codex on PR #899: lib/strategies/logic_arb.py:42 (get_no_price), lib/strategies/value_investor.py:30 (get_no_price), lib/strategies/weather_arb.py:25 (json), lib/strategies/weather_arb.py:29 (urllib.request), lib/strategy_base.py:34 (field). Cross-project audit required before cleanup — lib/ is shared with other projects (WARP-CodX, future tenants).
