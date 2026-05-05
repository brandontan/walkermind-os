Last Updated : 2026-05-06T01:21:39Z
Status       : P3b copy-trade strategy PR open (PR #877) — MAJOR tier, SENTINEL pending (Issue #878). Migration runner path decision needed before P3b merge. Paper-default. EXECUTION_PATH_VALIDATED NOT SET.

[COMPLETED]
- PR #852 — feat(crusaderbot): import full Replit build R1-R11
- PR #853 — sentinel: crusaderbot-replit-import PASS (post-fix)
- C1 resolved: KELLY_FRACTION applied, capital_alloc_pct capped <1.0
- C2 resolved: migrations/004 idempotent DO $$ blocks
- C3 resolved: Tier 3 promotion gated on MIN_DEPOSIT_USDC
- R12b — Fly.io health probes + operator alerts + JSON logging (PR #856 merged)
- PR #857 — chore: state sync post-PR #856
- PR #858 — chore: state sync post-PR #857
- PR #860 — chore: state sync post-PR #858
- PR #861 — chore: ROADMAP R12b drift fix + WORKTODO init (STANDARD, merged)
- R12a — CI/CD Pipeline GitHub Actions + Fly.io — PR #855 MERGED 2026-05-04 (STANDARD)
- R12c — Auto-Close / Take-Profit exit watcher — PR #865 MERGED 2026-05-05 (MAJOR, SENTINEL APPROVED 95/100)
- R12d — Telegram Position UX (live monitor + force close) — PR #868 MERGED 4f5e12201964 (STANDARD)
- R12e — Auto-Redeem System — PR #869 MERGED 7f8af0b90993 (MAJOR, SENTINEL CONDITIONAL 64/100 — conditions resolved PR #879)
- R12f — Operator Dashboard + Kill Switch + Job Monitor — PR #874 MERGED 2026-05-05 (STANDARD)
- P3a — Strategy Registry Foundation (BaseStrategy ABC + StrategyRegistry + migration 008) — PR #876 MERGED 2026-05-05 (STANDARD, FOUNDATION)

[IN PROGRESS]
- P3b — Copy Trade strategy — PR #877 OPEN — MAJOR tier, SENTINEL pending (Issue #878, label: agent:sentinel)
  Branch: WARP/CRUSADERBOT-P3B-COPY-TRADE, SHA: c4df48c7
  CI: Lint+Test PASS

[NOT STARTED]
- R12d — Live Opt-In Checklist (MAJOR — hard gate before EXE)
- R12e — Live → Paper Auto-Fallback (MAJOR)
- R12f — Daily P&L Summary (STANDARD)
- R12 — Deployment (Fly.io) final (MAJOR — blocked on all R12 lanes + P3 complete)
- P3c — Signal Following strategy (MAJOR)
- P3d — Per-user signal scan loop + execution queue wiring (MAJOR)

[NEXT PRIORITY]
- SENTINEL must run on PR #877 (Issue #878, label: agent:sentinel) before merge
- Migration runner path: database.run_migrations() reads migrations/ — 008_strategy_tables.sql at infra/migrations/ not applied at startup. WARP🔹CMD decision: move 008 to migrations/ or update runner before P3b (009) merge.
- After P3b merge: P3c → P3d → live activation sequence

[KNOWN ISSUES]
- Migration runner path: 008_strategy_tables.sql at infra/migrations/ — runner reads migrations/ only. Tables 008+009 never applied at startup. Fix required before P3b merge (WARP🔹CMD decision: move file vs update runner).
- /deposit no tier gate (intentional, non-blocking)
- services/* dead code (LOW, post-R12 cleanup)
- check_alchemy_ws is TCP-only (no full WS handshake) — surfaces DNS/SSL/firewall; full handshake is follow-up
- F401 unused imports: bot/dispatcher.py, bot/handlers/dashboard.py, cache.py, config.py, domain/risk/gate.py, scheduler.py (ruff cleanup lane, LOW)
