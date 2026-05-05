Last Updated : 2026-05-06 01:18
Status       : R12e SENTINEL audit closed — PR #879 merged, CONDITIONAL 64/100, conditions resolved. P3a strategy registry PR open. R12f operator dashboard PR open. R12c exit watcher (PR #865) awaiting SENTINEL + CMD merge. R12a CI/CD PR open. Paper-default. EXECUTION_PATH_VALIDATED NOT SET.

[COMPLETED]
- C1 resolved: KELLY_FRACTION applied, capital_alloc_pct capped <1.0
- C2 resolved: migrations/004 idempotent DO $$ blocks
- C3 resolved: Tier 3 promotion gated on MIN_DEPOSIT_USDC
- R12b — Fly.io health probes + operator alerts + JSON logging (PR #856 merged)
- PR #861 — chore(crusaderbot): ROADMAP R12b drift fix + WORKTODO init (STANDARD, merged)
- R12d — Telegram Position UX — PR #868 merged (4f5e12201964) — STANDARD
- R12e — Auto-Redeem System — PR #869 merged (7f8af0b90993) — MAJOR — NARROW INTEGRATION
- PR #879 — SENTINEL r12e-auto-redeem CONDITIONAL 64/100, conditions resolved (merged)

[IN PROGRESS]
- R12a — CI/CD Pipeline (GitHub Actions) — PR open: WARP/CRUSADERBOT-R12A-CICD-PIPELINE — STANDARD tier, awaiting WARP🔹CMD review
- R12c — Auto-Close / Take-Profit — PR open: WARP/CRUSADERBOT-R12C-EXIT-WATCHER — MAJOR tier, SENTINEL audit required before merge
- R12d — Telegram Position UX (live position monitor + per-position force close) — PR #868 MERGED (4f5e12201964) — STANDARD tier
- R12e — Auto-Redeem System — PR #869 + PR #879 MERGED — MAJOR tier, SENTINEL CONDITIONAL 64/100, conditions resolved — WARP🔹CMD final merge decision on GO-LIVE gate pending
- R12f — Operator Dashboard + Kill Switch + Job Monitor + Audit Log — PR open: WARP/CRUSADERBOT-R12F-OPERATOR-DASHBOARD — STANDARD tier, awaiting WARP🔹CMD review
- P3a — Strategy Registry Foundation (BaseStrategy ABC + StrategyRegistry + types + migration 008) — PR open: WARP/CRUSADERBOT-P3A-STRATEGY-REGISTRY — STANDARD tier, FOUNDATION ONLY, awaiting WARP🔹CMD review

[NOT STARTED]
- R12d — Live Opt-In Checklist (MAJOR — hard gate before EXE)
- R12e — Live → Paper Auto-Fallback (MAJOR)
- R12f — Daily P&L Summary
- R12 — Deployment (Fly.io) — final (MAJOR)

[NEXT PRIORITY]
- WARP🔹CMD review required for P3a strategy registry foundation. Source: projects/polymarket/crusaderbot/reports/forge/p3a-strategy-registry.md. Tier: STANDARD. Branch: WARP/CRUSADERBOT-P3A-STRATEGY-REGISTRY.
- WARP🔹CMD review required for R12f operator dashboard + kill switch. Source: projects/polymarket/crusaderbot/reports/forge/r12f-operator-dashboard.md. Tier: STANDARD. Branch: WARP/CRUSADERBOT-R12F-OPERATOR-DASHBOARD.
- R12c exit watcher (PR #865) CLEAN — WARP🔹CMD merge decision pending. Tier: MAJOR, SENTINEL required. Branch: WARP/CRUSADERBOT-R12C-EXIT-WATCHER.
- WARP•SENTINEL validation required for R12c exit watcher before merge. Source: projects/polymarket/crusaderbot/reports/forge/r12c-exit-watcher.md. Tier: MAJOR. Branch: WARP/CRUSADERBOT-R12C-EXIT-WATCHER.

[KNOWN ISSUES]
- /deposit no tier gate (intentional, non-blocking)
- services/* dead code (LOW, post-merge cleanup)
- check_alchemy_ws is TCP-only (no full WS handshake) to avoid pulling a websockets dep — surfaces DNS/SSL/firewall outages; full handshake is a follow-up
- P3a migration 008 placed at infra/migrations/ per WARP🔹CMD task spec; existing runner reads from migrations/ — WARP🔹CMD decision needed before P3b consumes the tables
