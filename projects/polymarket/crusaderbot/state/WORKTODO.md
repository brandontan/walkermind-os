# CrusaderBot -- WORKTODO

**Project:** projects/polymarket/crusaderbot
**Last Updated:** 2026-05-11 15:30

---

## Right Now

- Fast Track Track B (Copy Trade execution) MERGED PR #948. Track C (trade notifications) PR #947 open — WARP🔹CMD review required. Activation guards remain NOT SET.

---

## Fast Track Week 1 -- Core Trading Loop

- [x] Track A -- Trade Engine + TP/SL worker -- MERGED PR #942 (2026-05-11), MAJOR, FULL RUNTIME INTEGRATION. TradeEngine service layer; signal_scan_job routes through TradeEngine; 47 hermetic tests green.
- [x] Track B -- Copy Trade Execution -- MERGED PR #948 (2026-05-11), MAJOR. CopyTradeMonitor.run_once(), 020 migration, 25 hermetic tests green; P1 fixes applied.
- [x] Track C -- Trade Notifications -- PR #947 open; STANDARD, NARROW INTEGRATION; 16 hermetic tests green; WARP🔹CMD review required.
- [ ] Track D -- Risk Caps + Kill Switch hardening -- QUEUED; MAJOR; SENTINEL REQUIRED
- [ ] Track E -- Daily P&L Report -- QUEUED; STANDARD

Done condition: Track A merged + SENTINEL APPROVED; Track B through E sequenced after.

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
- [ ] R12 -- Deployment (Fly.io) final -- Lane 1B MERGED PR #901 (MAJOR, NARROW INTEGRATION, SENTINEL APPROVED 95/100). Lane 2C MERGED PR #907 (Telegram demo polish, CRU-6, MINOR, Claim NONE). Lane 1C MERGED PR #908 (2026-05-08) ca5f6f57 (STANDARD, NARROW INTEGRATION, SENTINEL APPROVED 98/100) -- migration 014 + seed/cleanup scripts + runbook, 514/514 tests green at merge. Operator prod verification pending per runbooks (Issue #900). Activation guards remain NOT SET.

Done condition: All R12 lanes merged + activation guards reviewed by WARP🔹CMD before final deployment.

---

## Phase 4 -- CLOB Integration

- [x] Phase 4A -- CLOB Adapter (auth + adapter + market data + mock + factory) -- MERGED PR #911 (2026-05-08), MAJOR, NARROW INTEGRATION, SENTINEL APPROVED 89/100
- [x] Ops Dashboard + Tier 2 Operator Seed -- MERGED PR #910 (2026-05-08) cabdc42f, STANDARD, NARROW INTEGRATION, SENTINEL NOT REQUIRED
- [x] Phase 4B -- Live Execution Rewire onto get_clob_client() / ClobClientProtocol -- MERGED PR #912 (2026-05-09) cb920661, MAJOR, NARROW INTEGRATION, SENTINEL APPROVED 92/100
- [x] Phase 4C -- Order Lifecycle (live polling + fills + paper touch+stale) -- MERGED PR #913 (2026-05-09) f326879d, MAJOR, NARROW INTEGRATION, SENTINEL APPROVED 96/100 FINAL at HEAD a484012

Done condition: Phase 4A-4C merged with USE_REAL_CLOB default False (paper-safe). Live activation gated on owner decision.

---

## Phase 5 -- Telegram Auto-Trade UX

- [x] Phase 5A -- Global menu handlers + 5-button main menu -- MERGED PR #924 (2026-05-10), MINOR, declared WARP/CRUSADERBOT-PHASE5A-GLOBAL-HANDLERS. _text_router priority fix, 5-button main menu, /settings command, my_trades view. 784/784 tests green.
- [x] Phase 5B -- Dashboard hierarchy redesign -- MERGED PR #926 (2026-05-10), STANDARD, declared WARP/CRUSADERBOT-PHASE5B-DASHBOARD, SENTINEL APPROVED 97/100. Single-message hierarchy, four sections, /start routing for existing Tier 2+ users.
- [x] Phase 5C -- Strategy preset system -- MERGED PR #925 (2026-05-10), MAJOR, WARP/CRUSADERBOT-PHASE5C-PRESETS, SENTINEL APPROVED 92/100. 3 presets (signal_sniper / value_hunter / full_auto), DB migration 016, paper-only activation enforced. 814/814 tests green.
- [x] Phase 5D -- 2-column grid + Copy/Auto Trade menu split -- MERGED PR #928 (2026-05-10), STANDARD. grid_rows() helper, main menu 5→6 buttons, 🐋 Copy Trade entry point, preset trim 5→3. 57/57 Phase 5D + preset tests green.
- [x] Phase 5E -- Copy Trade dashboard + wallet discovery -- MERGED PR #930 (2026-05-10), MAJOR, NARROW INTEGRATION, WARP/CRUSADERBOT-PHASE5E-COPY-TRADE. Dashboard empty state + task-list hierarchy, two-path wallet discovery (Paste Address + Discover leaderboard), wallet stats service (Gamma API + retry+backoff), migration 018, 24 hermetic tests. 903/903 tests green.
- [x] Phase 5I -- My Trades combined view -- MERGED PR #934 (2026-05-10), STANDARD, NARROW INTEGRATION. Combined positions + activity message, per-position close with confirmation (paper mode), full history pagination 10/page, 2-col keyboard grid, 13 hermetic tests. Report: projects/polymarket/crusaderbot/reports/forge/phase5i-my-trades.md.
- [x] Phase 5F -- Copy Trade setup wizard + per-task edit -- MERGED PR #935 (2026-05-10), MAJOR, NARROW INTEGRATION, 3-step wizard, ConversationHandler 5 states, CRUD, 33 hermetic tests.
- [x] Phase 5H -- First-time onboarding flow -- MERGED PR #937 (2026-05-10), STANDARD. ConversationHandler 5 states, migration 019 (onboarding_complete), QR code, 18 hermetic tests.

Done condition: Phase 5A-5I merged. No activation guard or risk gate constant changes; preset surface is paper-only; live activation requires Dashboard 2FA-gated toggle.

---

## Activation Guards (DO NOT TOUCH until explicit owner decision)

- EXECUTION_PATH_VALIDATED -- NOT SET
- CAPITAL_MODE_CONFIRMED -- NOT SET
- ENABLE_LIVE_TRADING -- NOT SET
- USE_REAL_CLOB -- NOT SET (default False, paper-safe)

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
