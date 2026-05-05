Last Updated : 2026-05-05 23:30 Asia/Jakarta
Status       : P3a strategy registry foundation built — PR open: WARP/CRUSADERBOT-P3A-STRATEGY-REGISTRY, STANDARD tier, awaiting WARP🔹CMD review. R12f operator dashboard PR open. R12e auto-redeem MERGED ✔ (PR #869). R12c exit watcher (PR #865) CLEAN, awaiting CMD merge. R12a CI/CD PR open. Paper-default. EXECUTION_PATH_VALIDATED NOT SET.

[COMPLETED]
- PR #852 — feat(crusaderbot): import full Replit build R1-R11
- PR #853 — sentinel: crusaderbot-replit-import PASS (post-fix)
- C1 resolved: KELLY_FRACTION applied, capital_alloc_pct capped <1.0
- C2 resolved: migrations/004 idempotent DO $$ blocks
- C3 resolved: Tier 3 promotion gated on MIN_DEPOSIT_USDC
- R12b — Fly.io health probes + operator alerts + JSON logging (PR #856 merged)
- PR #857 — chore(crusaderbot): state sync — PR #856 post-merge (WARP•ECHO routine)
- PR #858 — chore(crusaderbot): state sync — PR #857 post-merge (WARP•ECHO routine)
- PR #860 — chore(crusaderbot): state sync — PR #858 post-merge (WARP•ECHO routine)
- PR #861 — chore(crusaderbot): ROADMAP R12b drift fix + WORKTODO init (STANDARD, merged)

[IN PROGRESS]
- R12a — CI/CD Pipeline (GitHub Actions) — PR open: WARP/CRUSADERBOT-R12A-CICD-PIPELINE — STANDARD tier, awaiting WARP🔹CMD review
- R12c — Auto-Close / Take-Profit — PR open: WARP/CRUSADERBOT-R12C-EXIT-WATCHER — MAJOR tier, SENTINEL audit required before merge
- R12d — Telegram Position UX (live position monitor + per-position force close) — PR #868 MERGED (4f5e12201964) — STANDARD tier
- R12e — Auto-Redeem System (instant + hourly workers + redeem_queue + Settings UI) — PR #869 MERGED (7f8af0b90993) — MAJOR tier, SENTINEL APPROVED 92/100
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
